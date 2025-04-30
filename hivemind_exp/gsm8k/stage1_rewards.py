import os
import random
import re

import numpy as np

from hivemind_exp.hivemind_utils import HivemindNode


def extract_xml_answer(text: str) -> str:
    answer = text.split("<answer>")[-1]
    answer = answer.split("</answer>")[0]
    return answer.strip()


def count_xml(text) -> float:
    count = 0.0
    if text.count("<think>\n") == 1:
        count += 2
    if text.count("\n</think>\n") == 1:
        count += 2
    if text.count("\n<answer>\n") == 1:
        count += 2
        count -= len(text.split("\n</answer>\n")[-1]) * 0.001
    if text.count("\n</answer>") == 1:
        count += 2
        count -= (len(text.split("\n</answer>")[-1]) - 1) * 0.001
    return count


# Reward functions
def correctness_reward_func(
    prompts, completions, answer, weighting=10.0, logging=False, **kwargs
) -> list[float]:
    responses = [completion[0]["content"] for completion in completions]
    q = prompts[0][-1]["content"]
    extracted_responses = [extract_xml_answer(r) for r in responses]
    if (random.random() < 0.01) and logging:  # 1% chance to write samples into a file
        os.makedirs(
            f"model_output_samples/gsm8k_samples_from_{os.getenv('HOSTNAME')}",
            exist_ok=True,
        )
        log_file = os.path.join(
            "model_output_samples",
            f"gsm8k_samples_from_{os.getenv('HOSTNAME')}",
            "correctness_samples.txt",
        )
        with open(log_file, "a") as f:
            f.write("-" * 20)
            out_line = f"Question:\n{q}\n\nAnswer:\n{answer[0]}\n\nResponse:\n{responses[0]}\n\nExtracted:\n{extracted_responses[0]}"
            f.write(out_line)
    return [
        1.0 * weighting if r == a else 0.0 for r, a in zip(extracted_responses, answer)
    ]


def int_reward_func(completions, weighting=2.5, **kwargs) -> list[float]:
    responses = [completion[0]["content"] for completion in completions]
    extracted_responses = [extract_xml_answer(r) for r in responses]
    return [1.0 * weighting if r.isdigit() else 0.0 for r in extracted_responses]


def strict_format_reward_func(completions, weighting=2.5, **kwargs) -> list[float]:
    """Reward function that checks if the completion has a specific format."""
    pattern = r"^<think>\n.*?\n</think>\n<answer>\n.*?\n</answer>\n$"
    responses = [completion[0]["content"] for completion in completions]
    matches = [re.match(pattern, r) for r in responses]
    return [1.0 * weighting if match else 0.0 for match in matches]


def soft_format_reward_func(completions, weighting=2.5, **kwargs) -> list[float]:
    """Reward function that checks if the completion has a specific format."""
    pattern = r"<think>.*?</think>\s*<answer>.*?</answer>"
    responses = [completion[0]["content"] for completion in completions]
    matches = [re.match(pattern, r) for r in responses]
    return [1.0 * weighting if match else 0.0 for match in matches]


def xmlcount_reward_func(completions, weighting=5.0, **kwargs) -> list[float]:
    contents = [completion[0]["content"] for completion in completions]
    return [count_xml(c) * weighting for c in contents]

def top_k_cumulative_reward(
    prompts,
    completions,
    answer,
    logging=False,
    **kwargs,
) -> list[float]:
    """
    Dummy reward function that accumulates all rewards into one for prompt generation's top_k selector
    """
    correctness_reward = correctness_reward_func(
        prompts, completions, answer, logging=logging
    )
    int_reward = int_reward_func(completions)
    strict_format_reward = strict_format_reward_func(completions)
    soft_format_reward = soft_format_reward_func(completions)
    xmlcount_reward = xmlcount_reward_func(completions)
    total_reward = [
        sum(tup)
        for tup in zip(
            correctness_reward,
            int_reward,
            strict_format_reward,
            soft_format_reward,
            xmlcount_reward,
        )
    ]
    return total_reward


def hivemind_cumulative_reward(
    node: HivemindNode,
    prompts,
    completions,
    answer,
    logging=False,
    output_signal_selector="max",
    **kwargs,
) -> list[float]:
    # 1) Tính các sub-reward
    correctness_reward = correctness_reward_func(prompts, completions, answer, logging=logging)
    int_reward       = int_reward_func(completions)
    strict_fmt       = strict_format_reward_func(completions)
    soft_fmt         = soft_format_reward_func(completions)
    xmlcount         = xmlcount_reward_func(completions)

    # 2) Tổng hợp
    total_reward = [
        sum(vals) for vals in zip(
            correctness_reward,
            int_reward,
            strict_fmt,
            soft_fmt,
            xmlcount,
        )
    ]

    # 3) Chuẩn bị danh sách response
    responses = [c[0]["content"] for c in completions]

    # 4) Chọn output_data tùy selector
    question = prompts[0][-1]["content"]
    best_answer = None

    if output_signal_selector == "max":
        idx = int(np.argmax(total_reward))
        best_answer = responses[idx]

    elif output_signal_selector == "mean":
        mean_val = sum(total_reward) / len(total_reward)
        # tìm idx có reward gần mean nhất
        idx = min(range(len(total_reward)), key=lambda i: abs(total_reward[i] - mean_val))
        best_answer = responses[idx]

    else:
        # default: publish tất cả responses
        node.outputs = {
            "question": question,
            "answer": answer[0] if answer else None,
            "agent_answers": {node.key: responses},
        }
        node.rewards = total_reward
        return [0.0] * len(total_reward)

    # 5) Với max/mean, publish single best
    node.outputs = {
        "question": question,
        "answer": answer[0] if answer else None,
        "agent_answers": {node.key: best_answer},
    }
    node.rewards = total_reward

    # 6) luôn return zeros (reward đã được ghi vào node.rewards)
    return [0.0 for _ in total_reward]
