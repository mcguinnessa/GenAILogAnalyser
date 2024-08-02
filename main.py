import streamlit as st
from uuid import uuid4
import os
import json
import websocket
import requests

###################################################################
# Install websocket-client which doesn't appear to be autodetected
# pip install websocket-client
#
#To run, ensure Cross Site Request Forgery is disabled.
#streamlit run main.py --server.enableXsrfProtection=False 
###################################################################

API_TOKEN = os.environ['API_TOKEN']
SOCKET_URL = "wss://ws.generative.engine.capgemini.com/"
REST_URL = "https://api.generative.engine.capgemini.com/v1/llm/invoke"

WORKSPACE_ID = ""
PROVIDER = "azure"

MODEL = "openai.gpt-4o"


########################################################################
#
# Uploads file, filters on error and warning and then creates a single
# line of text with a maximum size
#
########################################################################
def preprocess_log_file(uploaded_file):
    """ Extract and summarize relevant information from the log file for GPT to use as context. """
    #os.write(1,b'preprocess_log_file.\n')
    print("preprocess_log_file")
    text = uploaded_file.read().decode('utf-8')  # Reading and decoding the log file
    #os.write(1,b'Uploaded.\n')
    print('Uploaded.')
    lines = text.splitlines()  # Split text into lines for processing
    #os.write(1,b'Lines split.\n')
    # Summarization strategy: Extract only error messages and warnings
    summarized_text = []
    for line in lines:
        if "error" in line.lower() or "warning" in line.lower():
            summarized_text.append(line)

    #os.write(1,b'Sumarized.\n')

    # Joining selected lines back into a single string
    result = "\n".join(summarized_text)
    return result[:15000]  # Limiting the result to fit within a manageable token size for the model

########################################################################
#
# Queries ChatGPT
#
########################################################################
def query_gpt(context, question):
    #os.write(1,b'Calling query_gpt.\n')
    print('Calling query_gpt.')
    """ Use GPT-3.5 Turbo to answer a question based on the log file context. """
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # Specifying the chat model
        messages=[
            {"role": "system", "content": "You are a helpful assistant trained to understand network logs."},
            {"role": "user", "content": context},
            {"role": "user", "content": question}
        ],
        temperature=0.5  # Adjust as needed for more deterministic responses
    )
    return response['choices'][0]['message']['content']


########################################################################
#
# Queries Generative Engine Using Websockets
#
########################################################################
def query_ge_ws(logextract, user_query):

   session_id = uuid4()

   url = SOCKET_URL
   ws = websocket.create_connection(url, header={"x-api-key": API_TOKEN})
   #os.write(1,b'Socket created.\n')


   context = f"""You are a helpful assistant trained to understand network logs. The following is an extract from a log file. I will refer to it in the next question. Please acknowlege receipt, but do not analyse until I provide a question. 

   Log Extract:{logextract}"""      

   send_query_ws(ws, session_id, context)

   prompt = f"""Given the previous log extract: {user_query}"""
   resp = send_query_ws(ws, session_id, prompt)

   # Close the WebSocket connection
   ws.close()
   return resp

########################################################################
#
# Queries Generative Engine Using REST
#
########################################################################
def query_ge_rest(logextract, user_query):

   headers = {
      "x-api-key": API_TOKEN,
      "Content-Type": "application/json",
      "Accept": "application/json"
   }

   session_id = uuid4()


#Please acknowlege receipt, but do not analyse until I provide a question. 
   context = f"""You are a helpful assistant trained to understand network logs. The following is an extract from a log file.

   Log Extract:{logextract}


   Given that context: {user_query}"""      

   resp = send_query_rest(session_id, headers, context)

   return resp

########################################################################
#
# Queries Using the REST API
#
########################################################################
def send_query_rest(session_id, headers, prompt):
   #os.write(1,b'\nCalling query_ge with ')
   #os.write(1,prompt.encode('utf-8'))
   #os.write(1,b'\n')
   # Session ID

   data = {
      "action":"run",
      "modelInterface":"langchain",
      "data": {
         "mode":"chain",
         "text": prompt,
         "files":[],
         "modelName": MODEL,
#           "provider":"bedrock",
         "provider": PROVIDER,
         "sessionId": str(session_id),
         "workspaceId": WORKSPACE_ID,
         "modelKwargs": {
            "streaming":False,
            "maxTokens":4096,
            "temperature":0.5,
            "topP":0.9
         }
      }
   }

   rc = "Unable to connect to Generative Engine"
   try:
      response = requests.post(REST_URL, headers=headers, json=data)

      if response.status_code == 200:
         #os.write(1,b'REST call successful.\n')
         #os.write(1,str(response.text).encode('utf-8'))
         print(response.text)

         if response.text.startswith("data:"):
            jobj = json.loads(response.text[6:])
            if "action" in jobj and jobj["action"] == "final_response":
               #os.write(1,str("Action exists and is final_response").encode('utf-8'))
               print("Action exists and is final_response")
               if "data" in jobj and "content" in jobj["data"]:
                  rc = jobj["data"]["content"]

      else:
         rc = "Error Response from Generative Engine:" + str(response.status_code)

   except Exception as e:
      #os.write(1,str(e).encode('utf-8'))
      rc = "Exception thrown during comms:" + str(e)

   return rc

########################################################################
#
# Queries Using the Wobsocket API
#
########################################################################
def send_query_ws(ws, session_id, prompt):
   #os.write(1,b'Calling query_ge.\n\n')
   # Session ID

   data = {
      "action":"run",
      "modelInterface":"langchain",
      "data": {
         "mode":"chain",
         "text": prompt,
         "files":[],
         "modelName": MODEL,
#           "provider":"bedrock",
         "provider": PROVIDER,
         "sessionId": str(session_id),
         "workspaceId": WORKSPACE_ID,
         "modelKwargs": {
            "streaming":False,
            "maxTokens":4096,
            "temperature":0.5,
            "topP":0.9
         }
      }
   }
   ws.send(json.dumps(data))

   r1 = None
   while r1 is None:
      m1 = ws.recv()
      j1 = json.loads(m1)
      a1 = j1.get("action")
      #os.write(1,str(j1).encode('utf-8'))
      #print("A1:" + str(a1))
      if "final_response" == a1:
         r1 = j1.get("data", {}).get("content")
         #print("Response: " + str(r1))
      if "error" == a1:
         print("M1:" + str(m1))

   #os.write(1,str(r1).encode('utf-8'))

   return r1

########################################################################
#
# MAIN
#
########################################################################
#os.write(1,b'Started.\n')
print('Started')
st.title('LLM based Network Log Analyzer for VMO2')

uploaded_file = st.file_uploader("Upload your network log file", type=['txt', 'log'])
if uploaded_file is not None:
   context = preprocess_log_file(uploaded_file)
   st.text_area("Extracted Context for AI", context, height=250)

   user_query = st.text_input("Enter your question about the log file:")
   if user_query:
      #answer = query_gpt(context, user_query)
      answer = query_ge_ws(context, user_query)
      #answer = query_ge_rest(context, user_query)

      st.write("Response:", answer)
