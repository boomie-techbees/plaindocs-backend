import json
import boto3
import base64
from boto3.dynamodb.conditions import Attr

REGION = 'us-east-1'
TABLE_NAME = 'plaindocs-analyses'

dynamodb = boto3.resource('dynamodb', region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

def decode_jwt_payload(token):
    try:
        payload = token.split('.')[1]
        padding = 4 - len(payload) % 4
        payload += '=' * padding
        decoded = base64.b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None

def lambda_handler(event, context):
    try:
        auth_header = event.get('headers', {}).get('authorization', '') or event.get('headers', {}).get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return {
                'statusCode': 401,
                'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Authentication required.'})
            }
        
        token = auth_header[7:]
        claims = decode_jwt_payload(token)
        
        if not claims:
            return {
                'statusCode': 401,
                'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Invalid token.'})
            }
        
        user_id = claims.get('sub')
        
        response = table.scan(
            FilterExpression=Attr('user_id').eq(user_id)
        )
        
        items = sorted(response.get('Items', []), key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(items)
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': str(e)})
        }
