from abc import ABC, abstractmethod
import os
import os.path as osp
import random
import subprocess
import json
import shutil
import sys

IMAGE_EXTS = (".png", ".jpg", ".jpeg")
CAD_ARTIFACTS = (
    ("tmp.step", "{i}_output.step"),
    ("tmp.stl", "{i}_output.stl"),
    ("tmp.png", "{i}_output.png"),
    ("tmp.svg", "{i}_output.svg"),
)


def _is_image_path(part):
    return isinstance(part, str) and part.lower().endswith(IMAGE_EXTS) and os.path.exists(part)


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _sanitize_api_messages(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in ("image_url", "url") and isinstance(value, str) and value.startswith("data:"):
                out[key] = f"[omitted data URL, {len(value)} chars]"
            else:
                out[key] = _sanitize_api_messages(value)
        return out
    if isinstance(obj, (list, tuple)):
        return [_sanitize_api_messages(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)

class GenerateResponseResult:
    def __init__(self, response_json=None, response_text=None, token_counts=None, thinking_text=None):
        self.response_json = response_json
        self.response_text = response_text
        self.token_counts = token_counts
        self.thinking_text = thinking_text

class BaseVLM(ABC):
    """
    A base class for Vision-Language Models (VLMs).
    """

    def __init__(self, config: dict, cache: bool = True):
        self.config = config
        self.cache = cache

    @abstractmethod
    def create_messages(self, inputs: list, sys=None) -> list:
        """
        Creates messages from interleaved inputs such as images and text.

        Args:
            inputs (list): A list of interleaved inputs (e.g., image paths, text).
        Returns:
            list: A list of formatted messages for the VLM.
        """
        pass


    @abstractmethod
    def generate_response(self, messages: list, output_path=None, return_token_counts=False) -> GenerateResponseResult:
        """
        Abstract method to generate a response based on the provided messages.

        Args:
            messages (list): A list of formatted messages for the VLM.

        Returns:
            str: The generated response.
        """
        pass

    def load_brep(self, brep_path: str) -> dict:
        """
        Loads a BREP file.

        Args:
            brep_path (str): Path to the BREP file.

        Returns:
            dict: A dictionary containing the loaded BREP data.
        """

        extension = os.path.splitext(brep_path)[1][1:]
        with open(brep_path, 'r') as f:
            brep_data = f.read()
        return {"type": extension, "content": brep_data}
  

    def run_single_edit_file_only(self, db, request_id, output_path: str) -> None:
        """
        Runs a single edit from text instruction and saves the output.

        Args:
            request_id (str): ID of the request to process.
            output_path (str): Path to save the output.
        """

        request = db.requests.find_one({"_id": request_id})
        if request is None:
            raise ValueError(f"Request ID {request_id} not found in the database.")
        
        brep_fn = db.breps.find_one({"_id": request["brep_start"]})[self.config["extension"]]
        if brep_fn is None:
            raise ValueError(f"BREP file not found for request ID {request_id}.")
        if not os.path.exists(brep_fn):
            raise ValueError(f"BREP file does not exist: {brep_fn}")

        brep = self.load_brep(brep_fn)
        instruction_text = request.get("text", "") or ""

        messages = self.create_messages(
            [f"Instruction text:\n{instruction_text}", f"brep file: {brep}", self.config["prompt"]],
            sys=self.config["system_prompt"],
        )
        response = self.generate_response(messages, output_path=output_path).response_json
        self.clean_up(messages)
        return response
    

    def run_rating_images(self, db, edit_id, output_path) -> None:
        """
        Runs a rating on an edit using text instruction and images.

        Args:
            edit_id (str): ID of the edit to rate.
            output_path (str): Path to save the rating in a json file.
        """
        edit_entry = db.edits.find_one({"_id": edit_id})

        request_entry = db.requests.find_one({"_id": edit_entry["request"]})

        if request_entry is None:
            return None

        start_brep_id = db.breps.find_one({"_id": request_entry["brep_start"]})
        start_breps = db.get_brep_images(start_brep_id["_id"], views=self.config["views_request"])
        start_breps = [osp.join(db.root_dir, start_brep) for start_brep in start_breps]

        end_brep_id = db.breps.find_one({"_id": edit_entry["brep_end"]})
        end_breps = db.get_brep_images(end_brep_id["_id"], views=self.config["views_edit"])
        end_breps = [osp.join(db.root_dir, end_brep) for end_brep in end_breps]

        if request_entry.get("text"):
            request_text = f"Instruction text:\n{request_entry['text']}"
        else:
            request_text = ""

        start = "Initial cad model: "
        end = "Edited cad model: "
        messages = self.create_messages(
            [
                request_text,
                start, 
                *start_breps,
                end,
                *end_breps,
                self.config["prompt"],
            ],
            sys=self.config["system_prompt"])
        response = self.generate_response(messages, output_path=output_path).response_json
        self.clean_up(messages)
        return response


    def run_ranking_images(self, db, request_id, output_path: str):
        """
        Runs a ranking on edits using text instruction and images.

        Args:
            request_id (str): ID of the request to rank edits for.
            output_path (str): Path to save the ranking in a json file.
        """
        start = "Initial cad model: "

        request_entry = db.requests.find_one({"_id": request_id})

        if request_entry.get("text"):
            request_text = f"Instruction text:\n{request_entry['text']}"
        else:
            request_text = ""
        
        start_breps = db.breps.find_one({"_id": request_entry["brep_start"]})
        start_breps = db.get_brep_images(start_breps["_id"], views=self.config["views_request"])
        start_breps = [osp.join(db.root_dir, start_brep) for start_brep in start_breps if start_brep]

        edit_iterator = db.edits.find({"request": request_id})

        edits_list = list(edit_iterator)
        
        # shuffle the edits list
        random.shuffle(edits_list)

        messages_list = [
                request_text,
                start, 
                *start_breps,
                self.config["prompt"],
            ]
        
        for i in range(len(edits_list)):
            messages_list.append(f"Edit {i}:")
            images = db.breps.find_one({"_id": edits_list[i]["brep_end"]})
            images = db.get_brep_images(images["_id"], views=self.config["views_edit"])
            for image in images:
                image = osp.join(db.root_dir, image)
                if not image:
                    raise ValueError(f"BREP file not found for edit ID {edits_list[i]["_id"]}.")
                messages_list.append(image)

        messages = self.create_messages(
            messages_list,
            sys=self.config["system_prompt"])
        response = self.generate_response(messages, output_path=output_path).response_json
        self.clean_up(messages)

        ranking = []
        try:
            if response is not None:
                for idx in response["ranking"]:
                    ranking.append(edits_list[idx]["_id"])
        except TypeError as e:
            print(f"Error processing response: {e}")

        return ranking
    

    def run_edit_cot_gen(self, db, edit_id, output_path) -> None:
        """
        Runs chain-of-thought generation for an edit using text instruction and images.

        Args:
            edit_id (str): ID of the edit to process.
            output_path (str): Path to save the output in a json file.
        """
        edit_entry = db.edits.find_one({"_id": edit_id})

        request_entry = db.requests.find_one({"_id": edit_entry["request"]})

        if request_entry is None:
            return None

        start_brep_id = db.breps.find_one({"_id": request_entry["brep_start"]})
        start_breps = db.get_brep_images(start_brep_id["_id"], views=self.config["views_request"])
        start_breps = [osp.join(db.root_dir, start_brep) for start_brep in start_breps]

        end_brep_id = db.breps.find_one({"_id": edit_entry["brep_end"]})
        end_breps = db.get_brep_images(end_brep_id["_id"], views=self.config["views_edit"])
        end_breps = [osp.join(db.root_dir, end_brep) for end_brep in end_breps]

        instruction_text = request_entry.get("text", "") or ""
        events = edit_entry.get("events", [])

        frames_dir = osp.join(db.root_dir, edit_entry["frames_dir"])

        if not osp.exists(frames_dir):
            frames = []
        else:
            frames = [f for f in os.listdir(frames_dir)]
            frames = [f for f in frames if any(f.endswith(ext) for ext in [".png", ".jpg", ".jpeg"])]
            frames = [osp.join(db.root_dir, frames_dir, frame) for frame in frames]


        combined_events_and_frames = []

        image_timestamps = [os.path.splitext(f)[0] for f in frames]
        image_timestamps = [os.path.basename(ts) for ts in image_timestamps]
        image_timestamps = [f.split('_')[-1] for f in image_timestamps]
        image_timestamps = [float(ts) for ts in image_timestamps]

        event_timestamps = [event['timestamp'] for event in events]

        # Combine and sort by timestamp. Output is a list of the ordered frame or event
        ts_frames = [(ts, f) for ts, f in zip(image_timestamps, frames)]
        ts_events = [(ts, e) for ts, e in zip(event_timestamps, events)]
        combined = ts_frames + ts_events
        combined.sort(key=lambda x: x[0])
        combined_events_and_frames = [str(item[1]) for item in combined]
        combined_ids = [f"ID: {i}" for i in range(len(combined_events_and_frames))]
        combined_events_and_frames = [val for pair in zip(combined_ids, combined_events_and_frames) for val in pair]

        message_list = []
        if "request" in self.config["fields"]:
            message_list.extend([
                f"Instruction text:\n{instruction_text}",
                "Initial cad model: ", 
                *start_breps,
            ])

        if "edit" in self.config["fields"]:
            message_list.extend([
                "Edited cad model: ", 
                *end_breps,
            ])

        if "frames" in self.config["fields"]:
            message_list.extend([
                "Images during the edit process: ",
                *frames,
            ])

        if "events" in self.config["fields"]:
            message_list.extend([
                f"Edit events: {events}",
            ])

        if "frame_event_interleaved" in self.config["fields"]:
            message_list.extend([
                "Images and events during the edit process: ",
                *combined_events_and_frames,
            ])

        message_list.append(
                self.config["prompt"],
        )

        messages = self.create_messages(
            message_list,
            sys=self.config["system_prompt"])
        
        response = self.generate_response(messages, output_path=output_path).response_json
        self.clean_up(messages)

        return response
    
    def run_rating_gen(self, db, edit_id, output_path: str) -> None:
        edit_entry = db.edits.find_one({"_id": edit_id})
        request_entry = db.requests.find_one({"_id": edit_entry["request"]})

        if request_entry is None:
            return None

        start_brep_id = db.breps.find_one({"_id": request_entry["brep_start"]})
        if start_brep_id:
            start_breps = db.get_brep_images(start_brep_id["_id"], views=self.config["views_request"])
            start_breps = [osp.join(db.root_dir, start_brep) for start_brep in start_breps]
        else:
            start_breps = []

        end_brep_id = db.breps.find_one({"_id": edit_entry["brep_end"]})
        end_breps = db.get_brep_images(end_brep_id["_id"], views=self.config["views_edit"])
        end_breps = [osp.join(db.root_dir, end_brep) for end_brep in end_breps]

        text_prompt = request_entry.get("text", "")
        if not text_prompt:
            text_prompt = request_entry.get("prompt", "")
        start = f"Requested generation: {text_prompt}."
        end = "Edited cad model: "
        messages = self.create_messages(
            [
                start,
                *start_breps,
                end,
                *end_breps,
                self.config["prompt"],
            ],
            sys=self.config["system_prompt"])
        response = self.generate_response(messages, output_path=output_path).response_json
        self.clean_up(messages)
        return response

    def clean_up(self, messages) -> None:
        pass


##########
########## Harnesses-specific functions
##########  
    def read_text_file(self, instruction_text_file):
        with open(instruction_text_file, 'r') as f:
            instruction_text = f.read()
        return instruction_text
    
    def load_task_info_dict(self, row):
        messages = []
        for k, v in row.items():
            messages.append(f"{k}: ")
            if v is None or v == "":
                messages.append("None")
            else:
                messages.append(v)

        return messages

    def _write_iteration_prompt_log(self, iteration_dir, iter_count, max_iters, prompt_parts, api_messages):
        prompt_records = []
        prompt_text_chunks = []
        image_index = 0
        for part in prompt_parts:
            if _is_image_path(part):
                dest_name = f"{iter_count}_prompt_image_{image_index}{osp.splitext(part)[1].lower()}"
                shutil.copy(part, os.path.join(iteration_dir, dest_name))
                prompt_records.append({"type": "image", "path": os.path.abspath(part), "copied_as": dest_name})
                prompt_text_chunks.append(f"[IMAGE {image_index}: {os.path.abspath(part)}]")
                image_index += 1
            else:
                text = part if isinstance(part, str) else str(part)
                prompt_records.append({"type": "text", "text": text})
                prompt_text_chunks.append(text)

        prompt_json_path = os.path.join(iteration_dir, f"{iter_count}_prompt.json")
        with open(prompt_json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "iteration": iter_count,
                    "max_iters": max_iters,
                    "part_count": len(prompt_records),
                    "parts": prompt_records,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        prompt_txt_path = os.path.join(iteration_dir, f"{iter_count}_prompt.txt")
        with open(prompt_txt_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(prompt_text_chunks))

        api_path = os.path.join(iteration_dir, f"{iter_count}_api_messages.json")
        with open(api_path, "w", encoding="utf-8") as f:
            json.dump(_sanitize_api_messages(api_messages), f, indent=2, ensure_ascii=False)

        print(f"Logged prompt to {prompt_txt_path}")
        return prompt_json_path

    def _write_iteration_vlm_log(self, iteration_dir, iter_count, whole_response, parsed_response):
        response_json_path = os.path.join(iteration_dir, f"{iter_count}_vlm_response.json")
        payload = {
            "iteration": iter_count,
            "response_text": whole_response.response_text,
            "thinking_text": whole_response.thinking_text,
            "response_json": _json_safe(whole_response.response_json),
            "parsed_response": _json_safe(parsed_response),
            "token_counts": whole_response.token_counts or {},
        }
        with open(response_json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        response_txt_path = os.path.join(iteration_dir, f"{iter_count}_vlm_response.txt")
        with open(response_txt_path, "w", encoding="utf-8") as f:
            f.write("=== thinking_text ===\n")
            f.write(whole_response.thinking_text or "")
            f.write("\n\n=== response_text ===\n")
            if isinstance(whole_response.response_text, str):
                f.write(whole_response.response_text)
            else:
                f.write(json.dumps(_json_safe(whole_response.response_text), indent=2, ensure_ascii=False))
        print(f"Logged VLM response to {response_txt_path}")

    def _copy_iteration_cad_artifacts(self, output_dir, iteration_dir, iter_count):
        copied = []
        missing = []
        for src_name, dest_template in CAD_ARTIFACTS:
            src = os.path.join(output_dir, src_name)
            dest = os.path.join(iteration_dir, dest_template.format(i=iter_count))
            if os.path.exists(src):
                shutil.copy(src, dest)
                copied.append(src_name)
            else:
                missing.append(src_name)
        print(f"CadQuery artifacts this iteration: exported={copied or ['none']} missing={missing}")
        return copied

    def visual_update_loop(self, instruction_text, task_info_dict, harness_script_file, output_dir, max_iters=10, run_function=None, conversation_instruction="", output_script_key=None, input_file=None, planning=None):
        if run_function is None:
            raise ValueError("run_function must be provided to visual_update_loop")
        
        messages = []

        messages.append(conversation_instruction)
        if planning:
            from .task_analysis import planning_message_parts
            messages.extend(planning_message_parts(planning))

        harness_script = self.read_text_file(harness_script_file)

        messages.append(harness_script)

        messages.append("Instruction:")
        messages.append(instruction_text)
        messages.append("Task information:")
        messages.extend(self.load_task_info_dict(task_info_dict))
        messages.append("Last output rendering: None (this is the first iteration)")

        iters_remaining = max_iters

        token_count_accumulator = {
        }

        iter_count = 0
        script = ""
        while iters_remaining > 0:
            print(f"\n========== Iteration {iter_count + 1}/{max_iters} ==========")
            messages.append(f"Iterations remaining: {iters_remaining}")
            iteration_dir = os.path.join(output_dir, "iteration_output")
            os.makedirs(iteration_dir, exist_ok=True)

            api_messages = self.create_messages(messages, sys=self.config["system_prompt"])
            self._write_iteration_prompt_log(
                iteration_dir, iter_count, max_iters, messages, api_messages
            )

            whole_response = self.generate_response(api_messages, return_token_counts=True)

            response = whole_response.response_json
            token_counts = whole_response.token_counts or {}

            for k in token_counts.keys():
                token_count_accumulator[k] = token_count_accumulator.get(k, 0) + token_counts[k]

            if isinstance(response, str):
                # find the part wrapped in ```json and ```. It might be in the middle of the response
                if "```json" in response:
                    response = response.split("```json")[1].split("```")[0]
                try:
                    response = json.loads(response)
                except json.JSONDecodeError as e:
                    print(f"Error parsing response as json: {e}")
                    response = {}

            if not isinstance(response, dict):
                print(f"VLM response was not a JSON object: {type(response)}")
                response = {}

            self._write_iteration_vlm_log(iteration_dir, iter_count, whole_response, response)

            script = response.get("my_cad_function", "") or ""
            complete = response.get("complete", False)

            function_path = os.path.join(iteration_dir, f"{iter_count}_function.py")
            with open(function_path, "w", encoding="utf-8") as f:
                f.write(script)

            if complete:
                print("Task completed (model set complete=true); CadQuery will not run this iteration.")
                with open(os.path.join(iteration_dir, f"{iter_count}_response.txt"), "w", encoding="utf-8") as f:
                    f.write("Thinking text:\n")
                    f.write(whole_response.thinking_text or "")
                    f.write("\n\nGenerated script:\n")
                    f.write(script)
                    f.write("\n\nProgram output:\nCadQuery skipped because complete=true.\n")
                break

            print("Running CadQuery...")
            program_output = run_function(script, harness_script_file, output_dir, input_file=input_file)
            print(program_output)

            copied = self._copy_iteration_cad_artifacts(output_dir, iteration_dir, iter_count)
            cadquery_ok = bool(copied)

            iteration_text_file = os.path.join(iteration_dir, f"{iter_count}_response.txt")
            with open(iteration_text_file, "w", encoding="utf-8") as f:
                f.write("Thinking text:\n")
                f.write(whole_response.thinking_text or "")
                f.write("\n\n")
                f.write("Generated script:\n")
                f.write(script)
                f.write("\n\nProgram output:\n")
                f.write(program_output)
                f.write("\n\nExported this iteration:\n")
                f.write(", ".join(copied) if copied else "none (CadQuery failed or returned no shape)")

            with open(os.path.join(iteration_dir, f"{iter_count}_cadquery.txt"), "w", encoding="utf-8") as f:
                f.write(program_output)

            messages.append("Program output from last iteration:")
            messages.append(program_output)
            messages.append("Visual output from last iteration:")

            image_fn = osp.join(output_dir, "tmp.png")
            if os.path.exists(image_fn):
                messages.append(image_fn)
            else:
                messages.append("None")
            messages.append("The function that you produced from the last iteration:")
            messages.append(script)

            print(f"Iteration {iter_count + 1} CadQuery export {'succeeded' if cadquery_ok else 'failed'}.")
            iters_remaining -= 1
            iter_count += 1

        input_tokens = float(token_count_accumulator.get("input_tokens", 0) or 0)
        output_tokens = float(token_count_accumulator.get("output_tokens", 0) or 0) + float(token_count_accumulator.get("thinking_tokens", 0) or 0)
        token_count_accumulator["cost_estimate"] = self.config["1m_token_cost_input"] * input_tokens / 1e6 + self.config["1m_token_cost_output"] * output_tokens / 1e6

        return_dict = {
            "token_counts": token_count_accumulator,
        }
        if output_script_key is not None:
            return_dict[output_script_key] = script
        return return_dict

    
##########
########## CadQuery specific methods for VLMs that generate CadQuery scripts
########## 
    def run_cadquery_script(self, script: str, harness_script_file: str, output_dir: str, input_file: str = None) -> str:
        # save script to temp file
        temp_script_file = os.path.join(output_dir, "temp_script.py")
        with open(temp_script_file, 'w') as f:
            f.write(script)

        cmd = [
            sys.executable,
            harness_script_file,
            "--output_dir",
            output_dir,
            "--function_file",
            temp_script_file
        ]

        if input_file is not None:
            cmd.extend(["--input_file", input_file])

        print(f"Running CadQuery script with command: {' '.join(cmd)}")
        # run command and capture output
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)

        # remove all stdout lines before the one that starts with "Loading function from"
        for line in result.stdout.splitlines():
            if line.startswith("Loading function from"):
                break
            else:
                result.stdout = result.stdout.replace(line + "\n", "")

        return f"stdout: {result.stdout}\nstderr: {result.stderr}"
    
    def cadquery_script(self, instruction_text, task_info_dict, harness_script_file, output_dir, max_iters=10):
        conversation_instruction = """
        Given the following instruction and task information, generate a CadQuery Python function that accomplishes the task.
        The script that runs the your function is provided for reference, as well as an example function, but you should only create your version of the function my_cad_function. Do not include any of the rest of the script.
        Once you have generated the function, it will be executed in CadQuery. You will then be provided with a rendering of the CAD model created by your function, and any prints, debug or error messages.
        You will then have the opportunity to refine your function based on this feedback, and it will be re-executed.
        Continue this process until the task is complete, or you reach the maximum number of iterations.

        If the task involves editing an existing model, the path to that model's .step file is passed to your function as args["input_file"], and is also listed as brep_start_path_step in the task information. Load it from args["input_file"] rather than hard-coding a path. For these cases, you might need to print out debug information once the model is loaded in your first iteration.

        Return a json object with two fields. Do not include any other text outside of the json object in your response:
        'complete': true if the task has been completed. IMPORTANT: This should only be judged by looking at the output from the last iteration, not whether a function has been returned this iteration. If there is no valid output that corresponds to the instruction, the task is not complete. The first iteration can never be complete. If this is true, then the current function will NOT be executed, and the function from the last iteration will be used.
        'my_cad_function': CadQuery python function as a string. Use the same definition and arguments as the example.
        Script:

        """

        input_file = None
        for key in ("brep_start_path_step", "brep_start_path_stp"):
            if task_info_dict.get(key):
                input_file = task_info_dict[key]
                break

        planning = None
        if self.config.get("run_planning", True):
            from .task_analysis import run_task_analysis
            planning = run_task_analysis(self, task_info_dict, output_dir)

        result = self.visual_update_loop(
            instruction_text=instruction_text,
            task_info_dict=task_info_dict,
            harness_script_file=harness_script_file,
            output_dir=output_dir,
            max_iters=max_iters,
            run_function=self.run_cadquery_script,
            conversation_instruction=conversation_instruction,
            input_file=input_file,
            planning=planning,
        )
        if planning and planning.get("token_counts"):
            acc = result.setdefault("token_counts", {})
            for key, value in planning["token_counts"].items():
                try:
                    acc[key] = acc.get(key, 0) + (value or 0)
                except TypeError:
                    acc[key] = value
            if "cost_estimate" in acc:
                input_tokens = float(acc.get("input_tokens", 0) or 0)
                output_tokens = float(acc.get("output_tokens", 0) or 0) + float(acc.get("thinking_tokens", 0) or 0)
                acc["cost_estimate"] = self.config["1m_token_cost_input"] * input_tokens / 1e6 + self.config["1m_token_cost_output"] * output_tokens / 1e6
        return result
    