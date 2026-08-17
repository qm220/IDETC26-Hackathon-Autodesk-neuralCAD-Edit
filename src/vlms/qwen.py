"""Qwen3-VL client for the CadQuery harness (local transformers or OpenAI-compatible API)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .base_vlm import BaseVLM, GenerateResponseResult

IMAGE_EXTS = (".png", ".jpg", ".jpeg")
THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
DEFAULT_LOCAL_MODEL = "Qwen/Qwen3-VL-8B-Instruct"


def _is_image_path(part: Any) -> bool:
    return isinstance(part, str) and part.lower().endswith(IMAGE_EXTS) and os.path.exists(part)


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = "\n".join(text.split("\n")[1:-1])
    elif text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1])
    return text.strip()


def _split_thinking(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    match = THINK_RE.search(text)
    if not match:
        return text.strip(), ""
    thinking = match.group(1).strip()
    answer = THINK_RE.sub("", text).strip()
    return answer, thinking


class VLM(BaseVLM):
    """Vision-language client for local Qwen3-VL-8B or a DashScope/vLLM API.

    Local defaults target an RTX 5090 (32 GB): Qwen3-VL-8B-Instruct in bfloat16 on CUDA.
    8B bf16 is ~16 GB, so 4-bit is unnecessary. 32B still does not fit.

    Config keys:
      family: "qwen"
      model: Hugging Face or API model id
      backend: "transformers" (local) or "openai" (vLLM / DashScope-compatible)
      device: "cuda" (default) / "cpu"
      torch_dtype: "bfloat16" (default on CUDA)
      load_in_4bit: bool (default False; 5090 has room for full 8B)
      enable_thinking: bool (default False for Instruct)
      max_new_tokens: int
      max_image_side: int (CAD screenshot cap; 1920 keeps harness PNG size)
      api_base: OpenAI-compatible base URL when backend is openai
    """

    def __init__(self, config: dict, cache: bool = True):
        super().__init__(config=config, cache=cache)
        self.config = config
        self.backend = config.get("backend", "transformers")
        self.enable_thinking = config.get("enable_thinking", False)
        self._model = None
        self._processor = None
        self._client = None
        self._device = "cuda"

        if self.backend == "openai":
            self._init_openai_backend()
        elif self.backend == "transformers":
            self._init_transformers_backend()
        else:
            raise ValueError(f"Unknown Qwen backend: {self.backend}. Use 'transformers' or 'openai'.")

    def _init_openai_backend(self) -> None:
        from openai import OpenAI

        api_key = (
            os.environ.get("QWEN_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or "EMPTY"
        )
        base_url = self.config.get("api_base") or os.environ.get(
            "QWEN_API_BASE", "http://127.0.0.1:8000/v1"
        )
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def _resolve_device(self) -> str:
        import torch

        requested = str(self.config.get("device", "cuda")).lower()
        if requested == "cpu":
            return "cpu"
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            print(f"Using CUDA GPU 0: {gpu_name} ({vram_gb:.1f} GB)")
            return "cuda"
        raise RuntimeError(
            "CUDA is not available, but this Qwen client is configured for an RTX 5090. "
            "In WSL, install/update the Windows NVIDIA driver with CUDA for WSL, then "
            "check `nvidia-smi` and `python -c 'import torch; print(torch.cuda.is_available())'`."
        )

    def _init_transformers_backend(self) -> None:
        import torch

        model_id = self.config.get("model", DEFAULT_LOCAL_MODEL)
        device = self._resolve_device()
        self._device = device
        load_in_4bit = bool(self.config.get("load_in_4bit", False)) and device == "cuda"

        dtype_name = self.config.get("torch_dtype")
        if not dtype_name:
            dtype_name = "bfloat16" if device == "cuda" else "float32"
        dtype = getattr(torch, dtype_name, torch.bfloat16)

        quant_note = "4-bit" if load_in_4bit else dtype_name
        print(f"Loading Qwen model {model_id} on {device} ({quant_note})...")

        from transformers import AutoProcessor

        self._processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)

        from_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
            "attn_implementation": self.config.get("attn_implementation", "sdpa"),
        }

        if load_in_4bit:
            from transformers import BitsAndBytesConfig

            from_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=dtype,
            )
            from_kwargs["device_map"] = {"": "cuda:0"}
        else:
            from_kwargs["dtype"] = dtype
            if device == "cuda":
                from_kwargs["device_map"] = {"": "cuda:0"}

        try:
            from transformers import Qwen3VLForConditionalGeneration

            self._model = Qwen3VLForConditionalGeneration.from_pretrained(model_id, **from_kwargs)
        except Exception:
            from transformers import AutoModelForImageTextToText

            self._model = AutoModelForImageTextToText.from_pretrained(model_id, **from_kwargs)

        if from_kwargs.get("device_map") is None:
            self._model = self._model.to(device)
        self._model.eval()
        print("Qwen model loaded.")

    def _model_device(self):
        if self._model is None:
            return self._device
        if hasattr(self._model, "device"):
            return self._model.device
        return next(self._model.parameters()).device

    def _load_image(self, path: str):
        from PIL import Image

        image = Image.open(path).convert("RGB")
        max_side = int(self.config.get("max_image_side", 1920))
        width, height = image.size
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / float(longest)
            image = image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
        return image

    def _messages_with_images(self, messages):
        converted = []
        for message in messages:
            content = []
            for part in message.get("content", []):
                if part.get("type") == "image":
                    image = part.get("image")
                    if isinstance(image, str):
                        image = self._load_image(image)
                    content.append({"type": "image", "image": image})
                else:
                    content.append(part)
            converted.append({"role": message["role"], "content": content})
        return converted

    def create_messages(self, inputs, sys=None):
        content = []
        for part in inputs:
            if part is None or part == "":
                continue
            if _is_image_path(part):
                content.append({"type": "image", "image": os.path.abspath(part)})
            else:
                content.append({"type": "text", "text": str(part)})

        messages = []
        system_prompt = sys if sys is not None else self.config.get("system_prompt")
        if system_prompt:
            messages.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})
        messages.append({"role": "user", "content": content})
        return messages

    def generate_response(self, messages, output_path=None, return_token_counts=False) -> GenerateResponseResult:
        if self.cache and output_path is not None and os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                raw = f.read()
            answer, thinking_text = _split_thinking(raw)
            parsed = _strip_json_fence(answer)
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError:
                pass
            result = GenerateResponseResult(
                response_json=parsed,
                response_text=answer,
                thinking_text=thinking_text,
                token_counts={"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "total_tokens": 0},
            )
            return result

        if self.backend == "openai":
            raw, token_counts = self._generate_openai(messages)
        else:
            raw, token_counts = self._generate_transformers(messages)

        answer, thinking_text = _split_thinking(raw)
        parsed = _strip_json_fence(answer)
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            pass

        if output_path is not None:
            with open(output_path, "w", encoding="utf-8") as f:
                if isinstance(parsed, dict):
                    json.dump(parsed, f, indent=4)
                else:
                    f.write(str(parsed))

        result = GenerateResponseResult(
            response_json=parsed,
            response_text=answer if isinstance(answer, str) else raw,
            thinking_text=thinking_text or "",
            token_counts=token_counts,
        )
        return result

    def _generate_openai(self, messages) -> tuple[str, dict]:
        api_messages = []
        for message in messages:
            role = message["role"]
            content = []
            for part in message["content"]:
                if part.get("type") == "image":
                    import base64

                    path = part["image"]
                    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                    with open(path, "rb") as img_file:
                        b64 = base64.b64encode(img_file.read()).decode("utf-8")
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        }
                    )
                else:
                    content.append({"type": "text", "text": part.get("text", "")})
            api_messages.append({"role": role, "content": content})

        extra_body = {
            "enable_thinking": self.enable_thinking,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        if "thinking_budget" in self.config:
            extra_body["thinking_budget"] = self.config["thinking_budget"]

        create_kwargs = {
            "model": self.config.get("model", "qwen3-vl-8b-instruct"),
            "messages": api_messages,
            "max_tokens": self.config.get("max_new_tokens", 8192),
            "temperature": self.config.get("temperature", 0.2),
            "extra_body": extra_body,
        }
        use_stream = self.config.get("stream", True)

        if use_stream:
            create_kwargs["stream"] = True
            create_kwargs["stream_options"] = {"include_usage": True}
            text_parts = []
            reasoning_parts = []
            usage = None
            for chunk in self._client.chat.completions.create(**create_kwargs):
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    text_parts.append(delta.content)
                if getattr(delta, "reasoning_content", None):
                    reasoning_parts.append(delta.reasoning_content)
            text = "".join(text_parts)
            reasoning = "".join(reasoning_parts)
        else:
            response = self._client.chat.completions.create(**create_kwargs)
            choice = response.choices[0].message
            text = choice.content or ""
            reasoning = getattr(choice, "reasoning_content", None) or ""
            usage = getattr(response, "usage", None)

        if reasoning and "<think>" not in text:
            text = f"<think>\n{reasoning}\n</think>\n{text}"

        token_counts = {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "thinking_tokens": 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }
        return text, token_counts

    def _prepare_transformers_inputs(self, messages):
        vision_messages = self._messages_with_images(messages)
        template_kwargs = {
            "tokenize": True,
            "add_generation_prompt": True,
            "return_dict": True,
            "return_tensors": "pt",
        }
        try:
            inputs = self._processor.apply_chat_template(
                vision_messages,
                enable_thinking=self.enable_thinking,
                **template_kwargs,
            )
        except TypeError:
            try:
                inputs = self._processor.apply_chat_template(vision_messages, **template_kwargs)
            except TypeError:
                prompt = self._processor.apply_chat_template(
                    vision_messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
                images = []
                for message in vision_messages:
                    for part in message.get("content", []):
                        if part.get("type") == "image":
                            images.append(part["image"])
                processor_kwargs = {
                    "text": [prompt],
                    "padding": True,
                    "return_tensors": "pt",
                }
                if images:
                    processor_kwargs["images"] = images
                inputs = self._processor(**processor_kwargs)
        return inputs.to(self._model_device())

    def _generate_transformers(self, messages) -> tuple[str, dict]:
        inputs = self._prepare_transformers_inputs(messages)
        max_new_tokens = int(self.config.get("max_new_tokens", 8192))
        temperature = float(self.config.get("temperature", 0.2))
        generated = self._model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature,
        )
        input_len = inputs["input_ids"].shape[1]
        new_tokens = generated[:, input_len:]
        text = self._processor.batch_decode(new_tokens, skip_special_tokens=True)[0]

        token_counts = {
            "input_tokens": int(input_len),
            "output_tokens": int(new_tokens.shape[1]),
            "thinking_tokens": 0,
            "total_tokens": int(input_len + new_tokens.shape[1]),
        }
        return text, token_counts
