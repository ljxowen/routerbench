---
task_categories:
- text-generation
- question-answering
language:
- en
tags:
- code
pretty_name: RouterBench
size_categories:
- 10K<n<100K
---

RouterBench is a dataset comprising of over 30000 prompts and the responses from 11 different LLMs, with the prompts taken from standard benchmarks such as MBPP, GSM-8k, Winogrande, Hellaswag, MMLU, MT-Bench, and more. 
The data includes the prompt, the model response, the estimated cost associated with that response, and a performance score to answer if the model got the answer correct. All prompts have a correct answer that the LLM generation
is compared against. These datasets are designed to be used with Martian's [routerbench](https://github.com/withmartian/alt-routing-methods/tree/public-productionize) package for training and evaluating various model routing
methods. 

There are two versions of the dataset, one where there is 5-shot generation, and one with 0-shot results. Both datasets can be used with the `routerbench` package individually or in combination.