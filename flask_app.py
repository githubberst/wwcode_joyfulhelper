import requests
import os, signal
from flask import Flask, request, render_template, abort
import openai
from dotenv import load_dotenv
import time

load_dotenv()

#######

fixed_contexts = {}
moving_contexts = {}
last_message = {}

init_context = [{
    'role':'system', 
    'content':""" 
    You are a warm, friendly and helpful AI assistant for migrant domestic workers on Facebook Messenger. You are named Joyful Helper. 
    Begin the conversation by greeting the user with 'Hi! Thank you for reaching out. Before I can assist you further' 
    Then, ask the following questions one at a time:
    1. 'May I know Which country are you from?'
    2. 'Which country are you working in now?'
    3. 'What is your preferred language to communicate in?'
    After gathering this information, ask what queries they have, and answer questions related to their concerns using only the latest official sources from the country that they are working in, 
    providing simple and clear answers in their chosen language. Make sure that the answer is translated well and makes sense. 
    If unsure of the answer, just state it explicitly that you are not sure. 
    """}]


def get_completion_from_messages(context,model="gpt-3.5-turbo", temperature=0):
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=context,
            temperature=temperature, 
        )
        print(response)
        return response.choices[0].message["content"]
    except Exception as e:
        print(f"Error: {e}")
        return "Sorry, there was an error processing your message."

def context_length(context):
    total_length = 0
    for i in range(0,len(context)):
        total_length += len(context[i]['content'])
    return total_length

def collect_messages(message,moving_context,fixed_context):
    prompt = message

    if len(fixed_context) < 10:
        fixed_context.append({'role':'user', 'content':f"{prompt}"})
    else:
        if (context_length(fixed_context)+context_length(moving_context) > 10000):
            moving_context.pop(0)
        moving_context.append({'role':'user', 'content':f"{prompt}"})
    
    total_context = fixed_context+moving_context

    response = get_completion_from_messages(total_context)
    if len(fixed_context) < 12:
        fixed_context.append({'role':'assistant', 'content':f"{response}"})
    else:
        moving_context.append({'role':'assistant', 'content':f"{response}"})

    print(f"fixed_length {context_length(fixed_context)}")
    print(f"moving_length {context_length(moving_context)}")

    
    return response



#######
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Integer, String, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
  pass

db = SQLAlchemy(model_class=Base)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///project.db"
app.config['SQLALCHEMY_ECHO'] = True
db.init_app(app)


class Context(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    contexts: Mapped[list] = mapped_column(type_=JSON)

#This is API key for OpenAI
openai.api_key = os.environ.get("OPENAI_API_KEY")
# This is page access token from facebook developer console. note - not using developer console anymore but using it as passcode for webhook authentication
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_TOKEN")
# This is API key for facebook messenger. note - not in use anymore
API="https://graph.facebook.com/v16.0/me/messages?access_token="+PAGE_ACCESS_TOKEN
# This is the verify token

with app.app_context():
    db.create_all()


@app.route('/webhook', methods=['GET'])
def verify():
    # Verify the webhook subscription with Facebook Messenger
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if not request.args.get("hub.verify_token") == "12345":
            return "Verification token missmatch", 403
        return request.args['hub.challenge'], 200
    return "Hello world", 200

@app.route("/webhook", methods=['POST'])
def fbwebhook():
    data = request.get_json()
    print(data)
    if not 'passcode' in data:
        abort(403)
        return
    if data['passcode'] != PAGE_ACCESS_TOKEN:
        abort(403)
        return
    try:
        if data['sender_id']:
            message = data['text']
            sender_id = data['sender_id']
            invocation_id = data['identifier']
            chat_gpt_input=message
            exists = Context.query.filter_by(user_id=sender_id).first()
            print(exists)
            if not exists:
                print(sender_id)
                db_contexts = Context(user_id=sender_id,contexts=init_context)
                db.session.add(db_contexts)
                db.session.commit()

            db_context_temp = Context.query.filter_by(user_id=sender_id).first()
            context_id = db_context_temp.id
            db_contexts = db.get_or_404(Context,context_id)

            saved_contexts = db_contexts.contexts.copy()
            print(saved_contexts)
            if len(saved_contexts) < 10:
                fixed_context = saved_contexts
                moving_context = []
            else:
                fixed_context = saved_contexts[0:9]
                moving_context = saved_contexts[10:]
                 
                                  
            # if sender_id not in fixed_contexts:
            #     fixed_contexts[sender_id] = init_context.copy()
            # #context = contexts[sender_id]
            # fixed_context = fixed_contexts[sender_id]
            # if sender_id not in moving_contexts:
            #     moving_contexts[sender_id] = []
            # moving_context = moving_contexts[sender_id]
            print(sender_id)
            print(chat_gpt_input)
            chatbot_res = collect_messages(chat_gpt_input,moving_context,fixed_context)
            print(fixed_context+moving_context)
            print("ChatGPT Response=>",chatbot_res)
            response = {
                'response': chatbot_res,
                'identifier': invocation_id
            }
            print(response)
            rr = requests.post("https://flows.messagebird.com/flows/invocations/webhooks/6a27176c-717c-4004-9af4-f8a34d0c258a", json=response)
            print(rr.text)
            print(db_contexts)
            db_contexts.contexts = fixed_context+moving_context
            print(db_contexts.contexts)
            db.session.commit()
            return response
    except Exception as e:
        print(e)
        pass
    
    return '200 OK HTTPS.'

@app.route("/privacy_policy", methods=['GET'])
def privacypolicy():
    return render_template('pp.jinja2')

  # Run the Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)