import json
import boto3
from botocore.config import Config

s3 = boto3.client('s3', 
    region_name='us-east-1',
    config=Config(signature_version='s3v4')
)
BUCKET = 'aussie-ecolens-media-3125'

def lambda_handler(event, context):
    body = json.loads(event.get('body', '{}'))
    filename = body.get('filename', f'file_{int(__import__("time").time())}')
    filetype = body.get('filetype', 'image/jpeg')
    
    key = f"uploads/{filename}"
    
    url = s3.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': BUCKET,
            'Key': key,
            'ContentType': filetype
        },
        ExpiresIn=300
    )
    
    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Content-Type': 'application/json'
        },
        'body': json.dumps({'url': url, 'key': key})
    }