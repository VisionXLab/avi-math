# -*- coding: utf-8 -*-
import os
import json
import shutil
import glob
import pdb
import requests
import re
import multiprocessing
import pandas as pd
import time
import argparse
import base64
# from openai import AzureOpenAI
import openai
import random
import tqdm


def folder_creat_if_not_exist(folder):
    if not os.path.exists(folder):
      os.makedirs(folder)
    
def find_files(base_dir,file_pattern='*.json'):
    # Use glob to recursively find all jpg files
    pattern_tmp = os.path.join(base_dir, '**', file_pattern)
    files_tmp = glob.glob(pattern_tmp, recursive=True)
    return files_tmp

def get_chat_completion(url, headers, payload, max_retries=5, retry_delay=3):
    retries = 0

    while retries < max_retries:
        response = requests.post(url, headers=headers, json=payload)
        
        # 检查响应状态码
        if response.status_code != 200:
            print(f"请求失败，状态码：{response.status_code}")
            retries += 1
            time.sleep(retry_delay)
            continue
        
        try:
            response_json = response.json()
            
            if 'choices' in response_json:
                json_content_formated_str = response_json['choices'][0]['message']['content']
                return json_content_formated_str
            else:
                print("响应中没有choices字段，重试...")
                retries += 1
                time.sleep(retry_delay)
        
        except ValueError:
            # 处理JSON解码错误
            print("响应不是有效的JSON，重试...")
            retries += 1
            time.sleep(retry_delay)

    raise Exception("重试次数达到上限，无法获取有效响应")

def encode_image(image_path):
  with open(image_path, "rb") as image_file:
    return base64.b64encode(image_file.read()).decode('utf-8')



def generate_response(row, source_dir, target_dir, vqa_processed):

    base64_image = encode_image(source_dir + row['image'])

    api_key="sk-proj-xxxxxx"
    
    headers = {
          "Content-Type": "application/json",
          "Authorization": f"Bearer {api_key}"
    }
    
    # step 1: planning
    sgPrompt = '''
    For the provided image and its associated question, generate a scene graph in JSON format that includes the following:
    1. Objects that are relevant to answering the question
    2. Object attributes that are relevant to answering the question
    3. Object relationships that are relevant to answering the question

    Scene Graph:
    '''      

    if row['qtype'] == 'multiple-choice':
        user_prompt = f"Question: {row['question']} Choices: {row['choices']}" + '\n' + sgPrompt
    elif row['qtype'] == 'yes/no':
        user_prompt = f"Question: {row['question']}" + '\n' + sgPrompt
    else:
        user_prompt = f"Question: {row['question']}" + '\n' + sgPrompt

    payload = {
      "model": "gpt-4o",
      "messages": [
        {
          "role": "system", 
          "content": f"",
          "role": "user",
          "content": [  
                { 
                    "type": "text", 
                    "text": f"{user_prompt}" 
                },
                { 
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ] 
        }
      ],
      "presence_penalty": 0,
      "frequency_penalty": 0,
      "max_tokens": 1000,
      "temperature": 0,
      "top_p": 0.99
    }
    outputs = get_chat_completion("https://api.openai.com/v1/chat/completions", headers, payload)
    row['outputs'] = outputs

    if row['qtype'] == 'multiple-choice':
        user_prompt =  "Scene Graph: " + outputs + "\n" + f"Use the image captured by a drone and scene graph to answer the question by choosing the best option. Question: {row['question']} Choices: {row['choices']}" 
    elif row['qtype'] == 'yes/no':
        user_prompt =  "Scene Graph: " + outputs + "\n" + f"Use the image captured by a drone and scene graph to answer the question. Question: {row['question']}"
    else:
        user_prompt =  "Scene Graph: " + outputs + "\n" + f"Use the image captured by a drone and scene graph to answer the question. Question: {row['question']}"

    if row['context'] != '':
        user_prompt = 'Context: ' + row['context'] + '\n' + user_prompt
    
    payload = {
      "model": "gpt-4o",
      "messages": [
        {
          "role": "system", 
          "content": f"",
          "role": "user",
          "content": [  
                { 
                    "type": "text", 
                    "text": f"{user_prompt}" 
                },
                { 
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ] 
        }
      ],
      "presence_penalty": 0,
      "frequency_penalty": 0,
      "max_tokens": 1000,
      "temperature": 0,
      "top_p": 0.99
    }
    previous_response = get_chat_completion("https://api.openai.com/v1/chat/completions", headers, payload)
    row['previous_response'] = previous_response

    # extract_answer
    if row['qtype'] == 'multiple-choice':
        user_prompt2 = f"Based on the question ({row['question']}) and reasoning provided in the output, conclude the final answer in the format 'Answer: $LETTER' (without quotes) where LETTER is one of ABCD."
    elif row['qtype'] == 'yes/no':
        user_prompt2 = f"Based on the question ({row['question']}) and reasoning provided in the output, conclude the final answer in the format 'Answer: Yes' or 'Answer: No' (without quotes)."
    else:
        user_prompt2 = f"Based on the question ({row['question']}) and reasoning provided in the output, conclude the final answer in the format 'Answer: XX' (without quotes)."

    payload = {
      "model": "gpt-4o",
      "messages": [
        {
            "role": "system", 
            "content": f""
        },
        # 上一轮模型的输出作为 assistant 消息
        {
            "role": "assistant",
            "content": f"{previous_response}"
        },
        # 用户的输入
        {
            "role": "user",
            "content": [  
                { 
                    "type": "text", 
                    "text": f"{user_prompt2}" 
                }
            ] 
        }
      ],
      "presence_penalty": 0,
      "frequency_penalty": 0,
      "max_tokens": 1000,
      "temperature": 0,
      "top_p": 0.99
    }
    response = get_chat_completion("https://api.openai.com/v1/chat/completions", headers, payload)
    row['response'] = response

    with open(target_dir + str(row['qid']) + '.json', 'w') as file:
        json.dump(row, file, indent=4)

def process_run(row, source_dir, target_dir, vqa_processed):
    try:
        if str(row['qid']) in vqa_processed:
            return
        print(row['qid'])
        generate_response(row, source_dir, target_dir, vqa_processed)
        return
    except Exception as e:
        print(f"Error in process_run: {e}")
        
if __name__ == "__main__":
    target_dir = f"/path/to/avi-math/gpt4o-ccot_extract_ans/"
    vqa_processed = find_files(target_dir,file_pattern='*.json')
    vqa_processed = [os.path.basename(file).split('.')[0] for file in vqa_processed]
    print(vqa_processed)
    folder_creat_if_not_exist(target_dir)
    source_dir = "/path/to/avi-math/images/"
    df = pd.read_json('/path/to/avi-math/label.json')
    rows_as_dicts = df.to_dict(orient='records')
#     for row in rows_as_dicts:
#         process_run(row, source_dir, target_dir, vqa_processed)
    with multiprocessing.Pool(processes=20) as pool:
        pool.starmap(process_run, [(row, source_dir, target_dir, vqa_processed) for row in rows_as_dicts])  
