import streamlit as st
from difflib import get_close_matches

# Define all relevant data
faq_data = {
    "mid exams portion": {
        "RL": "2 units",
        "BEFA": "2.5 units (3rd unit: cost concepts only, pages 16-22)",
        "IPR": "2.5 units",
        "DVT": "2.5 units (first two topics, 3rd unit: 8 pages)",
        "GENAI": "2 units"
    },
    "exam timetable": {
        "dates": "17-10-2024 to 19-10-2024",
        "sessions": {
            "forenoon": "10:00 A.M to 11:30 A.M",
            "afternoon": "2:00 P.M to 3:30 P.M"
        },
        "schedule": [
            {"date": "17-10-2024", "day": "Thursday", "forenoon": ["RL"], "afternoon": ["BEFA"]},
            {"date": "18-10-2024", "day": "Friday", "forenoon": ["DVT"], "afternoon": [ "GENAI"]},
            {"date": "19-10-2024", "day": "Saturday", "time": "10:00 A.M - 1:00 P.M", "subject": "IPR"}
        ]
    },
    "contact information": {
        "Monish": "+917032338726",
        "Shaistha": "+919410478221"
    },
    "cr_information": "Monish and Shaistha are the class representatives (CRs) for CSM-A.",
    "material link": "If you need 4-1 material, it will be available at https://vidyaa-beta.vercel.app/",
    "additional resources": {
        "4-1 Drive": "https://drive.google.com/drive/folders/1AuJkUA5e6uLX_9IcBQxv5MA_piSl8omg?usp=sharing",
        "Bulletin Board (Notice Board)": "https://notice-csma.vercel.app/",
        "Assist-Cell CSM-A (Grievance Cell)": "https://assistcellcsma.vercel.app/"
    }
}

# Keywords for matching questions
keywords = {
    "portion": ["portion", "units", "syllabus", "topics"],
    "timetable": ["timetable", "exam dates", "schedule"],
    "contact": ["contact", "number", "phone"],
    "material": ["material", "4-1", "resources"],
    "drive": ["drive", "folder", "documents"],
    "bulletin": ["bulletin", "notice", "board"],
    "assist-cell": ["assist-cell", "grievance", "help"],
    "cr": ["cr", "class representative", "class rep", "crs", "monish", "shaistha"],
    "units_query": ["material", "unit", "units", "be fa", "rl", "gen ai", "ipr", "dvt"]  # Added for unit-related queries
}

# Streamlit application layout
st.title("Student Query Chatbot")

user_input = st.text_input("Ask your question:")

# Function to find the best keyword match
def find_keyword_match(user_input):
    words = user_input.lower().split()
    for word in words:
        for key, variations in keywords.items():
            if get_close_matches(word, variations, n=1, cutoff=0.6):  # Fuzzy matching
                return key
    return None

# Function to generate a response based on matched keyword
def get_response(user_input):
    match = find_keyword_match(user_input)

    if match == "portion":
        response = "\n".join([f"{subject}: {info}" for subject, info in faq_data["mid exams portion"].items()])
    elif match == "timetable":
        timetable = faq_data["exam timetable"]
        response = f"Exam Dates: {timetable['dates']}\n"
        response += "Schedule:\n"
        for entry in timetable['schedule']:
            if 'forenoon' in entry and 'afternoon' in entry:
                subjects_forenoon = ", ".join(entry['forenoon']) if entry['forenoon'] else "N/A"
                subjects_afternoon = ", ".join(entry['afternoon']) if entry['afternoon'] else "N/A"
                time_info = ""
            else:
                subjects_forenoon = "N/A"
                subjects_afternoon = "N/A"
                time_info = f" Time: {entry.get('time', 'N/A')}"

            response += (f"{entry['date']} ({entry['day']}):\n"
                          f"  Forenoon: {subjects_forenoon}\n"
                          f"  Afternoon: {subjects_afternoon}{time_info}\n")
    elif match == "contact":
        response = "\n".join([f"{name}: {number}" for name, number in faq_data["contact information"].items()])
    elif match == "cr":
        response = faq_data["cr_information"]
    elif match == "material":
        response = faq_data["material link"]
    elif match == "units_query":
        response = "For unit materials, please visit: https://vidyaa-beta.vercel.app/"
    elif match == "drive":
        response = f"4-1 Drive: {faq_data['additional resources']['4-1 Drive']}"
    elif match == "bulletin":
        response = f"Bulletin Board (Notice Board): {faq_data['additional resources']['Bulletin Board (Notice Board)']}"
    elif match == "assist-cell":
        response = f"Assist-Cell CSM-A (Grievance Cell): {faq_data['additional resources']['Assist-Cell CSM-A (Grievance Cell)']}"
    else:
        response = "Sorry, I don't have the answer to that. Please try rephrasing your question."

    return response

# Generate response based on user input
if user_input:
    answer = get_response(user_input)
    st.write(answer)
