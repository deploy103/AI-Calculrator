import ast
import json
import math
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest


MODEL_NAME = "gpt-5.4"
ENV_CANDIDATE_PATHS = (
    Path(".env"),
    Path(".env/.env"),
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent.parent / ".env" / ".env",
)

ALLOWED_FUNCTIONS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
    "log10": math.log10,
    "ln": math.log,
    "abs": abs,
    "round": round,
}

ALLOWED_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}

ALLOWED_BINARY_OPERATORS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
)

ALLOWED_UNARY_OPERATORS = (
    ast.UAdd,
    ast.USub,
)


@dataclass
class CalculationPlan:
    expression: str
    formula_text: str
    explanation: str
    answer_unit: str


def load_openai_api_key():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if api_key:
        return api_key

    for env_path in ENV_CANDIDATE_PATHS:
        loaded_key = _read_api_key_from_file(env_path)
        if loaded_key:
            os.environ["OPENAI_API_KEY"] = loaded_key
            return loaded_key

    raise ValueError("OPENAI_API_KEY를 찾지 못했습니다. .env 또는 .env/.env 파일을 확인하세요.")


def _read_api_key_from_file(path):
    if not path.exists() or not path.is_file():
        return ""

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" in line:
            key, value = line.split("=", 1)
            if key.strip() == "OPENAI_API_KEY":
                return value.strip().strip('"').strip("'")

        if line.startswith("sk-"):
            return line

    return ""


class SafeEvaluator:
    def evaluate(self, expression):
        tree = ast.parse(expression, mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("숫자만 사용할 수 있습니다.")

        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, ALLOWED_BINARY_OPERATORS):
                raise ValueError("허용되지 않은 연산입니다.")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self._apply_binary_operator(node.op, left, right)

        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, ALLOWED_UNARY_OPERATORS):
                raise ValueError("허용되지 않은 단항 연산입니다.")
            value = self._eval_node(node.operand)
            return self._apply_unary_operator(node.op, value)

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("허용되지 않은 함수 호출입니다.")
            func_name = node.func.id
            if func_name not in ALLOWED_FUNCTIONS:
                raise ValueError("허용되지 않은 함수입니다.")
            args = [self._eval_node(arg) for arg in node.args]
            return ALLOWED_FUNCTIONS[func_name](*args)

        if isinstance(node, ast.Name):
            if node.id in ALLOWED_CONSTANTS:
                return ALLOWED_CONSTANTS[node.id]
            raise ValueError("허용되지 않은 상수입니다.")

        raise ValueError("해석할 수 없는 수식입니다.")

    def _apply_binary_operator(self, operator, left, right):
        if isinstance(operator, ast.Add):
            return left + right
        if isinstance(operator, ast.Sub):
            return left - right
        if isinstance(operator, ast.Mult):
            return left * right
        if isinstance(operator, ast.Div):
            return left / right
        if isinstance(operator, ast.Pow):
            return left ** right
        if isinstance(operator, ast.Mod):
            return left % right
        if isinstance(operator, ast.FloorDiv):
            return left // right
        raise ValueError("지원하지 않는 연산입니다.")

    def _apply_unary_operator(self, operator, value):
        if isinstance(operator, ast.UAdd):
            return +value
        if isinstance(operator, ast.USub):
            return -value
        raise ValueError("지원하지 않는 단항 연산입니다.")


class AIAgentCalculator:
    def __init__(self, model=MODEL_NAME, client=None):
        self.api_key = load_openai_api_key()
        self.client = client or ResponsesHTTPClient(api_key=self.api_key)
        self.model = model
        self.evaluator = SafeEvaluator()

    def make_plan(self, user_input):
        instructions = (
            "너는 자연어 계산 문제를 식으로 바꾸는 계산 도우미다. "
            "반드시 JSON만 출력해야 한다. "
            '형식은 {"expression":"","formula_text":"","explanation":"","answer_unit":""} 이다. '
            "expression에는 파이썬 수식만 넣어라. "
            "formula_text에는 사람이 읽기 좋은 계산식 설명을 넣어라. "
            "예를 들면 18 / 3 = 6 또는 12000 x (1 - 0.15) = 10200 같은 형식이다. "
            "explanation에는 왜 그 식이 맞는지 1~2문장으로 설명해라. "
            "사용 가능한 함수는 sin, cos, tan, sqrt, log10, ln, abs, round 이다. "
            "사용 가능한 상수는 pi, e 이다. "
            "퍼센트는 0.01을 곱해서 수식화해라. "
            "문제를 풀 수 없으면 expression을 빈 문자열로 두고 explanation에 이유를 써라."
        )

        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": "low"},
            instructions=instructions,
            input=user_input,
        )

        data = self._parse_json(response.output_text.strip())
        return CalculationPlan(
            expression=data.get("expression", "").strip(),
            formula_text=data.get("formula_text", "").strip(),
            explanation=data.get("explanation", "").strip(),
            answer_unit=data.get("answer_unit", "").strip(),
        )

    def solve(self, user_input):
        plan = self.make_plan(user_input)

        if not plan.expression:
            return {
                "question": user_input,
                "expression": "",
                "formula_text": "",
                "explanation": plan.explanation or "계산식을 만들지 못했습니다.",
                "result": "",
                "message": plan.explanation or "계산식을 만들지 못했습니다.",
            }

        result = self.evaluator.evaluate(plan.expression)
        result_value = self._normalize_result_value(result)
        result_text = self._format_result(result_value, plan.answer_unit)
        formula_text = self._merge_formula(plan.formula_text, result_text)
        explanation = plan.explanation or "질문을 계산식으로 바꿔서 결과를 구했습니다."
        message = self._build_message(formula_text, explanation, result_text)

        return {
            "question": user_input,
            "expression": plan.expression,
            "formula_text": formula_text,
            "explanation": explanation,
            "result": result_text,
            "message": message,
        }

    def _parse_json(self, text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("AI 응답을 JSON으로 읽지 못했습니다.")
            return json.loads(text[start:end + 1])

    def _normalize_result_value(self, result):
        if isinstance(result, float):
            result = round(result, 10)
            if result.is_integer():
                return int(result)
        return result

    def _format_result(self, result, answer_unit):
        if answer_unit:
            return f"{result} {answer_unit}"
        return str(result)

    def _merge_formula(self, formula_text, result_text):
        if not formula_text:
            return result_text
        if "=" in formula_text:
            return formula_text
        return f"{formula_text} = {result_text}"

    def _build_message(self, formula_text, explanation, result_text):
        parts = []
        if formula_text:
            parts.append(f"식: {formula_text}")
        if explanation:
            parts.append(f"설명: {explanation}")
        parts.append(f"결과: {result_text}")
        return "\n".join(parts)


class Level4CalculatorGUI:
    def __init__(self, root, tk_module, messagebox_module, scrolledtext_module):
        self.root = root
        self.tk = tk_module
        self.messagebox = messagebox_module
        self.scrolledtext = scrolledtext_module
        self.root.title("Level 4 AI Agent 계산기")
        self.root.geometry("980x720")
        self.root.configure(bg="#f4efe6")

        self.calculator = None
        self.history = []

        self.status_var = self.tk.StringVar(value="API 키를 확인하고 있습니다.")
        self.question_var = self.tk.StringVar()

        self._build_layout()
        self._load_calculator()

    def _build_layout(self):
        title = self.tk.Label(
            self.root,
            text="AI Agent Calculator",
            font=("Helvetica", 24, "bold"),
            bg="#f4efe6",
            fg="#202020",
        )
        title.pack(pady=(20, 8))

        subtitle = self.tk.Label(
            self.root,
            text="질문을 입력하면 식, 설명, 결과까지 함께 보여줍니다.",
            font=("Helvetica", 12),
            bg="#f4efe6",
            fg="#4f4a44",
        )
        subtitle.pack()

        input_frame = self.tk.Frame(self.root, bg="#f4efe6")
        input_frame.pack(fill="x", padx=24, pady=(20, 12))

        entry = self.tk.Entry(
            input_frame,
            textvariable=self.question_var,
            font=("Helvetica", 16),
            relief="solid",
            bd=1,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=10)
        entry.bind("<Return>", lambda event: self.solve_question())
        self.entry = entry

        ask_button = self.tk.Button(
            input_frame,
            text="계산하기",
            command=self.solve_question,
            font=("Helvetica", 13, "bold"),
            bg="#cc6b3d",
            fg="white",
            activebackground="#b75d31",
            activeforeground="white",
            padx=20,
            pady=9,
            relief="flat",
        )
        ask_button.pack(side="left", padx=(12, 0))
        self.ask_button = ask_button

        sample_frame = self.tk.Frame(self.root, bg="#f4efe6")
        sample_frame.pack(fill="x", padx=24)

        sample_questions = [
            "64개의 사과를 4명에게 똑같이 나누면 몇 개씩 가져가?",
            "12000원의 15% 할인가는 얼마야?",
            "반지름이 5인 원의 넓이를 구해줘",
        ]

        for question in sample_questions:
            button = self.tk.Button(
                sample_frame,
                text=question,
                command=lambda value=question: self._fill_sample(value),
                font=("Helvetica", 11),
                bg="#e6d5be",
                fg="#2d241d",
                relief="flat",
                padx=10,
                pady=8,
                wraplength=240,
                justify="center",
            )
            button.pack(side="left", padx=(0, 10), pady=(0, 14))

        content_frame = self.tk.Frame(self.root, bg="#f4efe6")
        content_frame.pack(fill="both", expand=True, padx=24, pady=(4, 24))

        left_panel = self.tk.Frame(content_frame, bg="#fffaf2", bd=1, relief="solid")
        left_panel.pack(side="left", fill="both", expand=True)

        right_panel = self.tk.Frame(content_frame, bg="#fffaf2", bd=1, relief="solid", width=260)
        right_panel.pack(side="left", fill="y", padx=(16, 0))
        right_panel.pack_propagate(False)

        output_title = self.tk.Label(
            left_panel,
            text="답변",
            font=("Helvetica", 16, "bold"),
            bg="#fffaf2",
            fg="#202020",
        )
        output_title.pack(anchor="w", padx=18, pady=(16, 8))

        output_box = self.scrolledtext.ScrolledText(
            left_panel,
            font=("Consolas", 13),
            wrap="word",
            relief="flat",
            bg="#fffaf2",
            fg="#222222",
            padx=10,
            pady=10,
        )
        output_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        output_box.config(state="disabled")
        self.output_box = output_box

        history_title = self.tk.Label(
            right_panel,
            text="최근 질문",
            font=("Helvetica", 16, "bold"),
            bg="#fffaf2",
            fg="#202020",
        )
        history_title.pack(anchor="w", padx=16, pady=(16, 8))

        history_list = self.tk.Listbox(
            right_panel,
            font=("Helvetica", 11),
            activestyle="none",
            relief="flat",
            bg="#fffaf2",
            fg="#2e2a27",
            highlightthickness=0,
        )
        history_list.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        history_list.bind("<<ListboxSelect>>", self._show_history_item)
        self.history_list = history_list

        status_bar = self.tk.Label(
            self.root,
            textvariable=self.status_var,
            font=("Helvetica", 11),
            anchor="w",
            bg="#202020",
            fg="#f7f3ed",
            padx=14,
            pady=8,
        )
        status_bar.pack(fill="x", side="bottom")

    def _load_calculator(self):
        try:
            self.calculator = AIAgentCalculator()
            self.status_var.set("준비 완료. 질문을 입력하면 식과 설명까지 함께 보여줍니다.")
        except Exception as error:
            self.calculator = None
            self.status_var.set("실행 준비 실패")
            self._set_output(str(error))
            self.messagebox.showerror("실행 준비 실패", str(error))

    def _fill_sample(self, question):
        self.question_var.set(question)
        self.entry.focus_set()

    def solve_question(self):
        question = self.question_var.get().strip()
        if not question:
            self.messagebox.showwarning("입력 필요", "질문을 입력하세요.")
            return

        if not self.calculator:
            self.messagebox.showerror("준비 실패", "API 키를 읽지 못해서 실행할 수 없습니다.")
            return

        self.ask_button.config(state="disabled")
        self.status_var.set("AI가 문제를 해석하고 있습니다.")
        self._set_output("계산 중입니다...\n잠시만 기다리세요.")

        worker = threading.Thread(target=self._solve_in_background, args=(question,), daemon=True)
        worker.start()

    def _solve_in_background(self, question):
        try:
            result = self.calculator.solve(question)
            self.root.after(0, lambda: self._handle_success(result))
        except Exception as error:
            self.root.after(0, lambda: self._handle_error(error))

    def _handle_success(self, result):
        self.ask_button.config(state="normal")
        self.status_var.set("계산이 완료되었습니다.")
        self._set_output(result["message"])
        self.history.insert(0, result)
        self.history_list.insert(0, result["question"])

    def _handle_error(self, error):
        self.ask_button.config(state="normal")
        self.status_var.set("오류가 발생했습니다.")
        self._set_output(str(error))
        self.messagebox.showerror("오류", str(error))

    def _show_history_item(self, event):
        selection = self.history_list.curselection()
        if not selection:
            return
        index = selection[0]
        self._set_output(self.history[index]["message"])
        self.status_var.set("이전 계산 기록을 보고 있습니다.")

    def _set_output(self, text):
        self.output_box.config(state="normal")
        self.output_box.delete("1.0", self.tk.END)
        self.output_box.insert(self.tk.END, text)
        self.output_box.config(state="disabled")


class ResponsesHTTPClient:
    def __init__(self, api_key):
        self.responses = ResponsesAPI(api_key)


class ResponsesAPI:
    def __init__(self, api_key):
        self.api_key = api_key

    def create(self, *, model, reasoning, instructions, input):
        payload = {
            "model": model,
            "reasoning": reasoning,
            "instructions": instructions,
            "input": input,
        }
        request = urlrequest.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlrequest.urlopen(request, timeout=60) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urlerror.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI API 요청 실패: {error.code} {error_body}") from error
        except urlerror.URLError as error:
            raise RuntimeError(f"OpenAI API 연결 실패: {error.reason}") from error

        output_text = response_data.get("output_text", "").strip()
        if not output_text:
            output_text = self._extract_text_from_output_items(response_data.get("output", []))
        if not output_text:
            raise RuntimeError("OpenAI 응답에서 output_text를 찾지 못했습니다.")

        return SimpleResponse(output_text)

    def _extract_text_from_output_items(self, output_items):
        text_parts = []

        for item in output_items:
            if item.get("type") != "message":
                continue

            for content_item in item.get("content", []):
                if content_item.get("type") == "output_text":
                    text = content_item.get("text", "")
                    if text:
                        text_parts.append(text)

        return "\n".join(text_parts).strip()


class SimpleResponse:
    def __init__(self, output_text):
        self.output_text = output_text


def run_cli():
    print("Level 4 AI Agent 계산기")
    print("종료하려면 exit 또는 quit 입력")

    try:
        calculator = AIAgentCalculator()
    except Exception as error:
        print(f"실행 준비 실패: {error}")
        return

    while True:
        user_input = input("\n질문 입력: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("계산기를 종료합니다.")
            break

        if not user_input:
            print("질문을 입력하세요.")
            continue

        try:
            result = calculator.solve(user_input)
            print(result["message"])
        except Exception as error:
            print(f"오류: {error}")


def run_gui():
    try:
        import tkinter as tk
        from tkinter import messagebox
        from tkinter import scrolledtext
    except ImportError as error:
        raise RuntimeError("이 환경에는 tkinter가 설치되어 있지 않아 GUI를 실행할 수 없습니다.") from error

    root = tk.Tk()
    Level4CalculatorGUI(root, tk, messagebox, scrolledtext)
    root.mainloop()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli()
    else:
        run_gui()
