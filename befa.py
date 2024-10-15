import streamlit as st
import pandas as pd

# Initialize quiz state
if 'score' not in st.session_state:
    st.session_state['score'] = 0
if 'current_question' not in st.session_state:
    st.session_state['current_question'] = 0
if 'selected_answers' not in st.session_state:
    st.session_state['selected_answers'] = []
if 'unit_selected' not in st.session_state:
    st.session_state['unit_selected'] = None

# Function to reset quiz
def reset_quiz():
    st.session_state['score'] = 0
    st.session_state['current_question'] = 0
    st.session_state['selected_answers'] = []

# Function to display MCQs
def display_mcq(question, options):
    st.write(question)
    selected_option = st.radio("Select an option:", options, key=st.session_state['current_question'])
    return selected_option

# Function to display Fill-in-the-Blanks
def display_fill_in_the_blanks(question):
    st.write(question)
    answer = st.text_input("Your answer:", key=f"fill_{st.session_state['current_question']}")
    return answer

# Function to calculate the quiz score
def calculate_score(mcq_questions, fill_in_the_blanks_questions):
    score = 0
    for i, question in enumerate(mcq_questions):
        if st.session_state['selected_answers'][i] == question['answer']:
            score += 1
    for j, question in enumerate(fill_in_the_blanks_questions):
        answer_index = len(mcq_questions) + j
        if st.session_state['selected_answers'][answer_index].strip().lower() == question['answer'].strip().lower():
            score += 1
    return score

# Function to generate correct answer sheet as text
def generate_answer_sheet(mcq_questions, fill_in_the_blanks_questions):
    lines = []
    for q in mcq_questions:
        lines.append(f"Q: {q['question']}\nCorrect Answer: {q['answer']}\n")
    for q in fill_in_the_blanks_questions:
        lines.append(f"Q: {q['question']}\nCorrect Answer: {q['answer']}\n")
    return "\n".join(lines)

# Quiz questions
unit_1_mcq_questions = [
    {
        "question": "1. Any human activity aimed at making profit is called:",
        "options": ["Partnership", "Social service", "Organization", "Business"],
        "answer": "Business"
    },
    {
        "question": "2. Business is always associated with:",
        "options": ["Profit", "Loss", "Risk", "None"],
        "answer": "Risk"
    },
    {
        "question": "3. If the entire business is managed and controlled by a single person, it is called:",
        "options": ["Sole trader ship", "Partnership", "Company", "Cooperative society"],
        "answer": "Sole trader ship"
    },
    {
        "question": "4. Winding up of partnership is referred to as:",
        "options": ["Dissolution", "Resolution", "Solution", "Closing"],
        "answer": "Dissolution"
    },
    {
        "question": "5. In Joint Stock Company, the maximum number of shareholders is:",
        "options": ["20", "50", "100", "Unlimited"],
        "answer": "Unlimited"
    },
    {
        "question": "6. Equity shares are also known as:",
        "options": ["Preference shares", "Ordinary shares", "Deferred shares", "Debentures"],
        "answer": "Ordinary shares"
    },
    {
        "question": "7. ______ is the father of economics:",
        "options": ["Karl Marx", "Max Muller", "Adams Smith", "None"],
        "answer": "Adams Smith"
    },
    {
        "question": "8. Indian economy is:",
        "options": ["Mixed economy", "Socialist economy", "Free economy", "None"],
        "answer": "Mixed economy"
    },
    {
        "question": "9. Business economics mainly deals with the ______ behavior of the firm:",
        "options": ["Economic", "Social", "Cost", "Profit"],
        "answer": "Economic"
    },
    {
        "question": "10. Production, Buying, and Selling are associated with:",
        "options": ["Partnership", "Sole tradership", "Company", "Business"],
        "answer": "Business"
    },
    {
        "question": "11. ______ is an artificial person created by law:",
        "options": ["Firm", "Company", "Partnership", "Cooperative society"],
        "answer": "Company"
    },
    {
        "question": "12. Excessive supply of money in the economy is called:",
        "options": ["Recession", "Overflow", "Inflation", "None"],
        "answer": "Inflation"
    },
    {
        "question": "14. In inflation, the value of money:",
        "options": ["Increases", "Decreases", "Stable", "None"],
        "answer": "Decreases"
    },
    {
        "question": "15. Demand pulls prices:",
        "options": ["Up", "Down", "Middle", "Stable"],
        "answer": "Up"
    },
    {
        "question": "16. If prices fall persistently, we call it:",
        "options": ["Deflation", "Inflation", "None"],
        "answer": "Deflation"
    },
    {
        "question": "17. The lowest point of the business cycle is called:",
        "options": ["Slump", "Depression", "Trough", "All"],
        "answer": "All"
    },
    {
        "question": "18. The total value of goods & services produced in an economy in a year is:",
        "options": ["National income", "State income", "Domestic income", "None"],
        "answer": "National income"
    },
    {
        "question": "19. GNP at market price minus depreciation is called:",
        "options": ["NNP at market price", "NNP at factor cost", "GDP", "None"],
        "answer": "NNP at market price"
    },
    {
        "question": "20. Built-in inflation is also called:",
        "options": ["Persistent inflation", "Hangover inflation", "Both a & b", "None"],
        "answer": "Both a & b"
    }
]


unit_2_mcq_questions = [
    {
        "question": "1. Elasticity of Demand is determined by all the factors except:",
        "options": ["Nature of commodity", "Proximity of substitutes", "Govt Policies", "Time"],
        "answer": "Govt Policies"
    },
    {
        "question": "2. What happens to Elasticity with time:",
        "options": ["Increase", "No change", "Decrease", "None"],
        "answer": "Increase"
    },
    {
        "question": "3. Price Elasticity is always:",
        "options": ["Negative", "Positive", "Consistent", "All of the above"],
        "answer": "Negative"
    },
    {
        "question": "4. If the price rises, demand:",
        "options": ["Rises", "Falls", "Doesn't change", "None"],
        "answer": "Falls"
    },
    {
        "question": "5. If Income Elasticity is positive and greater than one, it is a _______ good:",
        "options": ["Necessity good", "Inferior good", "Superior good", "None"],
        "answer": "Superior good"
    },
    {
        "question": "6. When any quantity can be sold at a given price and when there is no need to reduce the price, the demand is said to be:",
        "options": ["Perfectly elastic", "Perfectly inelastic", "Relatively elastic", "None"],
        "answer": "Perfectly elastic"
    },
    {
        "question": "7. Demand for Petrol is:",
        "options": ["Perfectly elastic", "Perfectly inelastic", "Relatively inelastic", "None"],
        "answer": "Relatively inelastic"
    },
    {
        "question": "8. Demand is determined by:",
        "options": ["Price of product", "Relative price of other goods", "Taste and habits", "All"],
        "answer": "All"
    },
    {
        "question": "9. The Law of Demand states that an increase in its price of goods:",
        "options": ["Increases quantity demanded", "Increases supply", "Decreases quantity demanded"],
        "answer": "Decreases quantity demanded"
    },
    {
        "question": "10. The Law of supply states that an increase in its price of goods:",
        "options": ["Increases quantity demanded", "Increases supply", "Decreases quantity demanded"],
        "answer": "Increases supply"
    },
    {
        "question": "11. Demand Forecasting is not governed by:",
        "options": ["Forecasting level", "Degree of orientation", "Degree of competition", "Market support"],
        "answer": "Market support"
    },
    {
        "question": "12. Forecast in view of total sales is viewed as a _______ forecast:",
        "options": ["Specific", "General", "Determined", "None"],
        "answer": "General"
    },
    {
        "question": "13. The demand curve always slopes:",
        "options": ["Upward", "Downward", "Linear", "None"],
        "answer": "Downward"
    },
    {
        "question": "14. If a company wants to elicit all the buyers' opinion, this method is called:",
        "options": ["Census", "Sampling", "Test marketing", "None"],
        "answer": "Census"
    },
    {
        "question": "15. Which of the following is not a trend projection method?",
        "options": ["Least square", "Moving average method", "Test marketing", "Trend projection"],
        "answer": "Test marketing"
    },
    {
        "question": "16. Under the _______ method, one set of data is used to predict another set:",
        "options": ["Least square", "Moving average method", "Test marketing", "Barometric technique"],
        "answer": "Barometric technique"
    },
    {
        "question": "17. _______ describes the degree of association between two variables:",
        "options": ["Correlation", "Regression", "Chi-square", "None"],
        "answer": "Correlation"
    },
    {
        "question": "18. The relation between price and supply in the law of supply is:",
        "options": ["Direct", "Inverse", "Proportionate", "None"],
        "answer": "Direct"
    },
    {
        "question": "19. _______ refers to predicting consumer future demand for products:",
        "answer": "Demand forecasting"
    },
    {
        "question": "20. _______ of a commodity refers to various quantities of the commodity which a seller is willing and able to sell at different prices in a given market:",
        "answer": "Supply"
    }
]


unit_1_fill_in_the_blanks = [
     {
        "question": "21. Price Index = current year's price / Base year's price * 100",
        "answer": "Price Index"
    },
    {
        "question": "22. CRR stands for ________.",
        "answer": "Cash Reserve Ratio"
    },
    {
        "question": "23. SLR stands for ________.",
        "answer": "Statutory Liquidity Ratio"
    },
    {
        "question": "24. Alternative waves of business expansion and contraction are called ________.",
        "answer": "Business cycle"
    },
    {
        "question": "25. A cooperative is a ________ organization.",
        "answer": "Non-profit"
    }
]
unit_2_fill_in_the_blanks = [
    {
        "question": "21. The rate of responsiveness in demand of a commodity for a given change in price is called _______",
        "answer": "Elasticity"
    },
    {
        "question": "22. In case of Unity elasticity, the elasticity is equal to _______",
        "answer": "1"
    },
    {
        "question": "23. Arc elasticity refers to the elasticity between two separate points on the _______",
        "answer": "Demand curve"
    },
    {
        "question": "24. _______ is an improvised method over the moving average method",
        "answer": "Exponential smoothing"
    },
    {
        "question": "25. Census method is called as the _______ method",
        "answer": "Enumeration"
    }
]
# Main app logic
st.title("BEFA Quiz Application")

# Unit selection
unit = st.selectbox("Select Unit for Quiz", ["Unit 1", "Unit 2"], key="unit_selector")
if st.session_state['unit_selected'] != unit:
    reset_quiz()
    st.session_state['unit_selected'] = unit

# Load questions based on the selected unit
if unit == "Unit 1":
    mcq_questions = unit_1_mcq_questions
    fill_in_the_blanks = unit_1_fill_in_the_blanks
else:
    mcq_questions = unit_2_mcq_questions
    fill_in_the_blanks = unit_2_fill_in_the_blanks

total_questions = len(mcq_questions) + len(fill_in_the_blanks)

# Display questions
if st.session_state['current_question'] < len(mcq_questions):
    current_mcq = mcq_questions[st.session_state['current_question']]
    selected_option = display_mcq(current_mcq['question'], current_mcq['options'])
    if st.button("Next"):
        st.session_state['selected_answers'].append(selected_option)
        st.session_state['current_question'] += 1
elif st.session_state['current_question'] < total_questions:
    current_fill_in_the_blanks = fill_in_the_blanks[st.session_state['current_question'] - len(mcq_questions)]
    answer = display_fill_in_the_blanks(current_fill_in_the_blanks['question'])
    if st.button("Next"):
        st.session_state['selected_answers'].append(answer)
        st.session_state['current_question'] += 1
else:
    st.write("Quiz Completed!")
    st.session_state['score'] = calculate_score(mcq_questions, fill_in_the_blanks)
    st.write(f"Your score: {st.session_state['score']} out of {total_questions}")

    # Download correct answers as text
    if st.button("Download Correct Answer Sheet"):
        answer_sheet = generate_answer_sheet(mcq_questions, fill_in_the_blanks)
        st.download_button("Download Answer Sheet", answer_sheet, "answer_sheet.txt", "text/plain")

    if st.button("Reset Quiz"):
        reset_quiz()

# Footer with copyright notice
st.markdown("---")  # Horizontal line for separation
st.markdown("<p style='text-align: center; font-size: 12px;'>© Monish KMIT. All Rights Reserved.</p>", unsafe_allow_html=True)        
