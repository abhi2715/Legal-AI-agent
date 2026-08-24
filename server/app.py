import json
from io import StringIO

from flask import Flask, jsonify, request
from flask_cors import CORS
from textblob import TextBlob

from paraphrase import paraphrase
from predict import run_prediction

app = Flask(__name__)
CORS(app)
answers = []


@app.route('/health')
def health():
    return jsonify({"status": "ok"})




def load_questions_short():
    questions_short = []
    with open('data/questions_short.txt', encoding="utf8") as f:
        questions_short = f.readlines()


    return questions_short


def getContractAnalysis(selected_response):
    print(selected_response)
    
    if selected_response == "":
        return "No answer found in document"
    else:
        blob = TextBlob(selected_response)
        polarity = blob.sentiment.polarity
        print(polarity)

        if polarity > 0:
            return "Positive"
        elif polarity < 0:
            return "Negative"
        else:
            return "Neutral"



questions_short = load_questions_short()



@app.route('/questionsshort')
def getQuestionsShort():
    # Ensure proper JSON response
    return jsonify(questions_short)




from agent import LegalAgent
import pypdf
import hashlib

agent = LegalAgent()
last_processed_hash = None

@app.route('/contracts/', methods=["POST"])
def getContractResponse():
    question = request.form.get('question', '')
    
    if 'file' in request.files and request.files['file'].filename != '':
        file = request.files["file"]
        
        paragraph = ""
        if file.filename.lower().endswith('.pdf'):
            try:
                reader = pypdf.PdfReader(file.stream)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        paragraph += text + "\n"
            except Exception as e:
                print(f"Error parsing PDF: {e}")
        else:
            paragraph = file.read().decode("utf-8", errors="replace")

        
        # Cache mechanism to prevent re-embedding the same document on every question
        if len(paragraph) > 0:
            doc_hash = hashlib.md5(paragraph.encode('utf-8')).hexdigest()
            global last_processed_hash
            if doc_hash != last_processed_hash:
                print("Embedding document into Vector DB...")
                agent.process_document(paragraph)
                last_processed_hash = doc_hash
            else:
                print("Document already embedded. Skipping FAISS generation...")
            
    if not question:
        return "Please ask a question."

    print("Running Agent...")
    result = agent.run(question)
    
    # We return the new structured result
    # We format it to match the UI expectations or update the UI to handle it.
    return jsonify(result)

 




@app.route('/contracts/paraphrase/<path:selected_response>', methods=['GET'])
def getContractParaphrase(selected_response):
    print(selected_response)
    
    if selected_response == "":
        return "No answer found in document"
    else:
        print('getting paraphrases')
        paraphrases = paraphrase(selected_response)
        print(paraphrases)
        return jsonify(paraphrases)

@app.route('/get_response', methods=['POST'])
def get_response():
    question = request.form['selected_response']
    with open('responses.json', 'r') as file:
        # json.load expects a file object, not a path string
        responses = json.load(file)
        for response in responses:
            if response['question'] == question:
                return response['answer']
    
    return "Response not found"

if __name__ == '__main__':
    app.run(port=5001)