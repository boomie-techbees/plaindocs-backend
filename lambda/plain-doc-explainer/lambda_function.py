import json
import boto3
import base64
import urllib.request
import urllib.error
import uuid
from datetime import datetime

def decode_jwt_payload(token):
    try:
        payload = token.split('.')[1]
        padding = 4 - len(payload) % 4
        payload += '=' * padding
        decoded = base64.b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None

REGION = 'us-east-1'
MODEL_ID = 'us.amazon.nova-lite-v1:0'
MAX_BYTES = 4 * 1024 * 1024  # 4MB

bedrock = boto3.client('bedrock-runtime', region_name=REGION)

SYSTEM_PROMPT = """You are a document explainer. You MUST respond entirely in {language}. Every word of your response must be in {language}, including all labels, descriptions, and the summary. Do not use English unless {language} is English.

Analyze the document and return ONLY a JSON object with exactly these fields:
- summary: a short paragraph explaining what this document is
- keyRights: array of objects with "label" and "description" fields
- keyRisks: array of objects with "label" and "description" fields
- watchOutFor: array of objects with "label" and "description" fields
- otherNotable: array of objects with "label" and "description" fields (use only if something important doesn't fit above, otherwise return empty array)

Return only valid JSON. No markdown, no code fences, no preamble."""

def fetch_url(url):
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        content_type = response.headers.get('Content-Type', '')
        content = response.read(MAX_BYTES)
        is_pdf = 'application/pdf' in content_type
        return content, is_pdf

def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        text = body.get('text', '')
        doc_base64 = body.get('document', '')
        url = body.get('url', '')
        language = body.get('language', 'English')

        user_id = None
        auth_header = event.get('headers', {}).get('authorization', '') or event.get('headers', {}).get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            claims = decode_jwt_payload(token)
            if claims:
                user_id = claims.get('sub')

        prompt = SYSTEM_PROMPT.format(language=language)

        if url:
            content, is_pdf = fetch_url(url)
            if is_pdf:
                messages = [{
                    "role": "user",
                    "content": [
                        {
                            "document": {
                                "format": "pdf",
                                "name": "fetched-doc",
                                "source": {
                                    "bytes": content
                                }
                            }
                        },
                        {"text": "Explain this document using the format specified."}
                    ]
                }]
            else:
                text_content = content.decode('utf-8', errors='ignore')
                messages = [{
                    "role": "user",
                    "content": [{"text": f"Explain this document using the format specified:\n\n{text_content}"}]
                }]
        elif doc_base64:
            messages = [{
                "role": "user",
                "content": [
                    {
                        "document": {
                            "format": "pdf",
                            "name": "uploaded-doc",
                            "source": {
                                "bytes": base64.b64decode(doc_base64)
                            }
                        }
                    },
                    {"text": "Explain this document using the format specified."}
                ]
            }]
        else:
            messages = [{
                "role": "user",
                "content": [{"text": f"Explain this document using the format specified:\n\n{text}"}]
            }]

        response = bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": prompt}],
            messages=messages,
            guardrailConfig={
                'guardrailIdentifier': 'r3n8beoeuevq',
                'guardrailVersion': 'DRAFT',
                'trace': 'enabled'
            }
        )
        
        stop_reason = response.get('stopReason', '')
            
        if stop_reason == 'guardrail_intervened':
            return {
                'statusCode': 400,
                'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'This document couldn\'t be processed. It may contain content that violates our usage guidelines.'})
            }

        result_text = response['output']['message']['content'][0]['text']

        result_text = result_text.strip()
        if result_text.startswith('```'):
            result_text = result_text.split('\n', 1)[1]
        if result_text.endswith('```'):
            result_text = result_text.rsplit('```', 1)[0].strip()

        result_json = json.loads(result_text)

        dynamodb = boto3.resource('dynamodb', region_name=REGION)
        table = dynamodb.Table('plaindocs-analyses')
        table.put_item(Item={
            'id': str(uuid.uuid4()),
            'timestamp': datetime.utcnow().isoformat(),
            'input_type': 'url' if url else 'pdf' if doc_base64 else 'text',
            'language': language,
            'summary_preview': result_json.get('summary', '')[:200],
            'user_id': user_id or 'anonymous'
        })        

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result_json)
        }

    except urllib.error.HTTPError as e:
        if e.code == 403:
            error_msg = "This URL blocked outside access. Try downloading the file and uploading it as a PDF instead."
        elif e.code == 404:
            error_msg = "That URL couldn't be found. Check the link and try again."
        else:
            error_msg = f"This URL couldn't be accessed (error {e.code}). Try downloading the file and uploading it as a PDF instead."
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': error_msg})
        }
    except urllib.error.URLError as e:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': "This URL couldn't be reached. Check the link or try downloading the file and uploading it as a PDF instead."})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': str(e)})
        }
