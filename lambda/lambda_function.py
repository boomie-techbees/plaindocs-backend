import json
import boto3
import base64
import urllib.request
import urllib.error

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
            messages=messages
        )

        result_text = response['output']['message']['content'][0]['text']
        result_text = result_text.strip()
        if result_text.startswith('```'):
            result_text = result_text.split('\n', 1)[1]
        if result_text.endswith('```'):
            result_text = result_text.rsplit('```', 1)[0].strip()

        result_json = json.loads(result_text)

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result_json)
        }

    except urllib.error.URLError as e:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': f'Could not fetch URL: {str(e)}'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': str(e)})
        }
