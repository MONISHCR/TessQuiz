import argparse
import requests
import os
import shutil

from PyPDF2 import PdfMerger
from PyPDF2.errors import PdfReadError
import fpdf


BEARER_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlcnJvciI6ZmFsc2UsInVzZXJuYW1lIjoiMjFCRDFBNjc2MSIsInN1YiI6MzQ5LCJyb2xlIjoiU1RVREVOVCIsImNvbGxlZ2VJZCI6MSwiY29sbGVnZU5hbWUiOiJLTUlUIiwibmFtZSI6IlZBSVNITkFWSSBWRU1VTEEiLCJpYXQiOjE3MjcyODE5ODIsImV4cCI6MTcyNzMwMzU4Mn0.yXWcZBLOo9De0iwpUjXPqZ11I9BRUasVD9FlZBM7dCg"

def main():

    parser = argparse.ArgumentParser(description="A simple command-line tool.")
    
    # Add the arguments
    parser.add_argument("-s", dest="subId", type=int, help="Sub ID")
    parser.add_argument("-n", dest="subName", type=str, help="Sub Name")
    parser.add_argument("-u", dest="unitId", type=int, help="Unit ID")
    parser.add_argument("-b", dest="bearerToken", type=str, help="Bearer Token")
    parser.add_argument("-p", dest="unitSavePath", type=str, help="Path to save Unit")

    args = parser.parse_args()

    sub_id = args.subId
    sub_name = args.subName
    unit_id = args.unitId
    bearer_token = args.bearerToken
    unit_path = args.unitSavePath

    # if BEARER_TOKEN is None:
    #     raise ValueError("Bearer Token is required.")

    if unit_id is None:
        fetchBySubject(sub_id, sub_name, bearer_token)
    else:
        topic_dict = fetchTopics(unit_id, bearer_token)
        saveUnitToLocal(unit_path, topic_dict, sub_name)

# def fetchByUnit(unit_id, bearer_token):

def fetchBySubject(subId, sub_name, bearerToken):
    unit_dict = fetchUnits(subId, bearerToken)
    for unit_name, unit_id in unit_dict.items():
        topics = fetchTopics(unit_id, bearerToken)
        unit_dict[unit_name] = topics

    saveToLocal(sub_name, subId, unit_dict)

def fetchUnits(sub_id, bearer_token):
    url = f"https://api.tesseractonline.com/studentmaster/get-subject-units/{sub_id}"
    bearer_token = BEARER_TOKEN

    headers = {
        "Authorization": f"{bearer_token}"
    }

    response = requests.get(url, headers=headers)
    data = response.json()
    if data.get('payload') is None:
        print("❌ Invalid Bearer Token")
        return
    
    unit_dict = {unit['unitName']: unit['unitId'] for unit in data['payload']}
    print(f"📚 {len(unit_dict)} units fetched")
    return unit_dict

def fetchTopics(unit_id, bearer_token):
    url = f"https://api.tesseractonline.com/studentmaster/get-topics-unit/{unit_id}"
    bearer_token = BEARER_TOKEN

    headers = {
        "Authorization": f"{bearer_token}"
    }

    response = requests.get(url, headers=headers)
    data = response.json()

    topic_dict = {topic['name']: [topic['pdf'], topic['refvideourl']] for topic in data['payload']['topics']}
    print("📖", len(topic_dict), "topics metadata fetched")
    return topic_dict

def saveUnitToLocal(unit_path, topics, unit_name):
    if unit_path is None or unit_path.strip() == "":
        print("⚠️ Unit Path is not provided, saving in current directory")
        unit_path = "./"

    # check if unit_path exist
    os.makedirs(unit_path + "/temp")

    if not os.path.exists(unit_path):
            print("🚫 Given Path does not exist, Aborted")
    
    print(f"📁 {unit_path} created")
    saveTopics(topics=topics, save_path=unit_path)
    remove_dir(unit_path)
    print("📚", unit_path, "saved")


def saveTopics(topics, save_path):

    topicId = 1
    unit = []
    for topic_name, topic_data in topics.items():
        pdf = fetchPDF(topic_data[0])
        
        # Creating topic page
        createPDF(topic_name, save_path + "/temp", topicId, topic_data[1])
        unit.append(save_path + f"/temp/{topicId}.pdf")
        topicId += 1

        # creating topic pdf
        temp_pdf = save_path + f"/temp/{topicId}.pdf"
        with open(temp_pdf, "wb") as file:
            file.write(pdf)
        file.close()
        unit.append(temp_pdf)

        topicId += 1
        print(f"✅ {topic_name} fetched")
    
    merger = mergePDFs(unit)
    merger.write(save_path +f".pdf")
    merger.close()

    

def saveToLocal(sub_name, sub_id, unit_dict):
    if sub_name is None or sub_name.strip() == "":
        print("⚠️ Subject Name is not provided, using Subject ID as name")
        sub_name = sub_id

    try:
        os.mkdir(f"./{sub_name}")
    except FileExistsError:
        print(f"⚠️ {sub_name} already exists")
        choice = input(f"❓ Do you want to overwrite {sub_name}. Y/N: ")
        if choice.lower() == "y":
            remove_dir(f"./{sub_name}")
        else:
            print("🚫 Aborted")
            return
        
    print(f"📁 {sub_name} created")
    
    for unit_name, topics in unit_dict.items():
        os.makedirs(f"./{sub_name}/{unit_name}")
        os.makedirs(f"./{sub_name}/{unit_name}/temp")

        saveTopics(topics=topics, save_path=f"./{sub_name}/{unit_name}")
        print("📚", unit_name, "saved")
        remove_dir(f"./{sub_name}/{unit_name}")


def fetchPDF(pdf_url):
    url = f"https://api.tesseractonline.com/{pdf_url}"
    response = requests.get(url)
    data = response.content
    return data

def mergePDFs(unit):
    merger = PdfMerger()
    for topic in unit:
        try:
            merger.append(topic)
        except PdfReadError:
            print("❌ Failed to read PDF. Probably content is not uploaded.")

    return merger

def remove_dir(directory):
    shutil.rmtree(directory)

def createPDF(topic_name, directory, topic_id, url):
    pdf = fpdf.FPDF(format='letter')
    pdf.add_page()
    pdf.set_font("Arial", size=20)
    pdf.cell(200, 10, txt=f"{topic_name}, \n", ln=10, align="C")

    if url is None:
        print(f"❌ URL not found for {topic_name}")
        pdf.output(directory + f"/{topic_id}.pdf")
        return
              
    # Add hyperlink to the URL
    pdf.set_text_color(0, 0, 255)  # Set text color to blue for hyperlink
    pdf.set_font("", "U")  # Set font style to underline for hyperlink
    pdf.cell(200, 10, txt=url, ln=1, link=url, align="C")  # Add the URL as a hyperlink
    pdf.set_text_color(0)  # Reset text color
    pdf.set_font("")  # Reset font style
    pdf.output(directory + f"/{topic_id}.pdf")

if __name__ == "__main__":
    main()