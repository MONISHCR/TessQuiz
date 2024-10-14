import streamlit as st
import requests
import json
import time

# Function to get quiz score
def get_score(quiz_id, access_token):
    url = "https://api.tesseractonline.com/quizattempts/submit-quiz"
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': access_token
    }
    payload = {"quizId": quiz_id}

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["payload"]["score"]
    except Exception as e:
        st.error(f"Error getting score: {e}")
        return None

# Function to attempt a quiz question and get the correct option
def attempt_quiz(quiz_id, question_id, current_score, access_token):
    options = ['a', 'b', 'c', 'd']
    correct_option = None

    for option in options:
        payload = {
            "quizId": quiz_id,
            "questionId": question_id,
            "userAnswer": option
        }
        try:
            new_score = attempt_quiz_api(quiz_id, payload, access_token)
            if new_score == current_score + 1:
                correct_option = option
                break
        except Exception as e:
            st.error(f"Error attempting quiz question {question_id}: {e}")
            break

    return correct_option

def attempt_quiz_api(quiz_id, payload, access_token):
    url = "https://api.tesseractonline.com/quizquestionattempts/save-user-quiz-answer"
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': access_token
    }

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return get_score(quiz_id, access_token)

# Function to fetch topics for a given unit ID
def get_unit_topics(unit_id, access_token):
    url = f"https://api.tesseractonline.com/studentmaster/get-topics-unit/{unit_id}"
    headers = {'Authorization': access_token}

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()

    return [
        {"topicId": topic["id"], "topicName": topic["name"]}
        for topic in data["payload"]["topics"] if topic["contentFlag"]
    ]

# Function to handle the result of a quiz
def result_quiz(topic_id, access_token):
    url = f"https://api.tesseractonline.com/quizattempts/quiz-result/{topic_id}"
    headers = {'Authorization': access_token}

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["payload"]["badge"] == 1

# Function to attempt all quizzes for the given topics
def attempt_one_quiz(quiz_id, topic_name, access_token):
    url = f"https://api.tesseractonline.com/quizattempts/create-quiz/{quiz_id}"
    headers = {'Authorization': access_token}

    response = requests.get(url, headers=headers)
    data = response.json()
    quiz_Id = data["payload"]["quizId"]

    quiz_content = f"Quiz: {topic_name}\n\n"
    current_score = 0

    for question in data["payload"]["questions"]:
        question_id = question["questionId"]
        question_text = question["question"]
        options = question["options"]

        # Log the question, options, and correct answer
        quiz_content += f"Question ID: {question_id}\n"
        quiz_content += f"Question: {question_text}\nOptions:\n"
        for key, value in options.items():
            quiz_content += f"{key}: {value}\n"

        # Attempt question and find correct option
        correct_option = attempt_quiz(quiz_Id, question_id, current_score, access_token)
        if correct_option:
            current_score += 1

        quiz_content += f"Correct Option: {correct_option or 'Not found'}\n\n"

    return quiz_content

# Streamlit UI
st.title("🤖 TessBot - Quiz Automation")

access_token = st.text_input("Access Token", type="password", placeholder="Bearer XXXXXXXXXXX")
unit_id = st.text_input("Unit ID", placeholder="Enter space-separated Unit IDs")

if st.button("Submit"):
    if not access_token or not unit_id:
        st.error("Please enter both Access Token and Unit ID.")
    else:
        unit_ids = unit_id.split()
        all_content = ""

        try:
            for unit in unit_ids:
                topics = get_unit_topics(unit, access_token)

                for topic in topics:
                    if result_quiz(topic["topicId"], access_token):
                        st.write(f"Quiz with ID {topic['topicId']} is already done!")
                        all_content += f"Quiz with ID {topic['topicId']} is already done!\n\n"
                    else:
                        st.write(f"Attempting quiz {topic['topicId']}...")
                        content = attempt_one_quiz(topic["topicId"], topic["topicName"], access_token)
                        all_content += content
                        st.success(f"Quiz {topic['topicId']} completed.")

            # Save the content to a text file and provide download option
            timestamp = int(time.time())
            file_name = f"quiz_results_{timestamp}.txt"
            with open(file_name, "w") as f:
                f.write(all_content)

            with open(file_name, "rb") as f:
                st.download_button(
                    label="Download Quiz Results",
                    data=f,
                    file_name=file_name,
                    mime="text/plain"
                )
        except Exception as e:
            st.error(f"Error: {e}")
