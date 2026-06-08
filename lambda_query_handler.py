import json
import boto3
from boto3.dynamodb.conditions import Attr
from decimal import Decimal
import re
import hashlib
import base64
import urllib.request as urlreq

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('MediaFiles')
s3 = boto3.client('s3')

EC2_ML_URL = 'http://98.91.206.44:5000/predict'


def extract_tag_name(key):
    key = str(key).strip()
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12};', key, re.IGNORECASE):
        return None
    if ';' in key:
        return None
    name = key.lower().strip()
    if re.match(r'^[a-z][a-z\s\-]{1,49}$', name):
        return name
    return None


def clean_tags(raw_tags):
    cleaned = {}
    if not raw_tags:
        return cleaned

    if isinstance(raw_tags, str):
        for part in raw_tags.split(','):
            part = part.strip()
            if ':' in part:
                name, _, count = part.partition(':')
                name = name.strip().lower()
                if name and re.match(r'^[a-z][a-z\s\-]{1,49}$', name):
                    try:
                        cleaned[name] = Decimal(str(int(float(count.strip()))))
                    except:
                        pass
            elif part:
                name = part.strip().lower()
                if re.match(r'^[a-z][a-z\s\-]{1,49}$', name):
                    cleaned[name] = Decimal('1')
        return cleaned

    if isinstance(raw_tags, list):
        for item in raw_tags:
            name = extract_tag_name(str(item))
            if name:
                cleaned[name] = Decimal('1')
        return cleaned

    if isinstance(raw_tags, dict):
        for key, val in raw_tags.items():
            tag_name = extract_tag_name(key)
            if not tag_name:
                continue
            if isinstance(val, dict) and 'N' in val:
                try:
                    count = Decimal(val['N'])
                except:
                    count = Decimal('0')
            elif isinstance(val, (int, float)):
                count = Decimal(str(val))
            elif isinstance(val, Decimal):
                count = val
            elif isinstance(val, str):
                try:
                    count = Decimal(str(int(float(val))))
                except:
                    count = Decimal('0')
            else:
                count = Decimal('0')
            if count > Decimal('0'):
                cleaned[tag_name] = max(cleaned.get(tag_name, Decimal('0')), count)

    return cleaned

def scan_all():
    """Full table scan with pagination."""
    items = []
    resp = table.scan()
    items += resp.get('Items', [])
    while 'LastEvaluatedKey' in resp:
        resp = table.scan(ExclusiveStartKey=resp['LastEvaluatedKey'])
        items += resp.get('Items', [])
    return items


def respond(status, body):
    return {
        'statusCode': status,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': 'POST,GET,OPTIONS',
            'Content-Type': 'application/json'
        },
        'body': json.dumps(body, default=str)
    }


def lambda_handler(event, context):
    try:
        print(f"RAW EVENT: {json.dumps(event)}")

        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        elif isinstance(event.get('body'), dict):
            body = event['body']
        else:
            body = event

        query_type = body.get('query_type', '')
        print(f"query_type={query_type}")

        if   query_type == 'check_upload': return handle_check_upload(body)
        elif query_type == 'tags':         return handle_tags(body)
        elif query_type == 'thumbnail':    return handle_thumbnail(body)
        elif query_type == 'query_file':   return handle_query_file(body)
        elif query_type == 'edit':         return handle_edit(body)
        elif query_type == 'delete':       return handle_delete(body)
        else:
            return respond(400, {'error': f'Unknown query_type: "{query_type}"'})

    except Exception as e:
        import traceback
        print(f"FATAL: {traceback.format_exc()}")
        return respond(500, {'error': str(e)})

def handle_check_upload(body):
    checksum = body.get('checksum', '').strip()
    s3_url   = body.get('s3_url', '').strip()

    if checksum:
        resp = table.scan(FilterExpression=Attr('checksum').eq(checksum))
        items = resp.get('Items', [])
        while 'LastEvaluatedKey' in resp:
            resp = table.scan(FilterExpression=Attr('checksum').eq(checksum),
                              ExclusiveStartKey=resp['LastEvaluatedKey'])
            items += resp.get('Items', [])
        if items:
            return respond(200, {'exists': True, 'duplicate': True,
                                 's3_url': items[0].get('s3_url', '')})

    if s3_url:
        resp  = table.scan(FilterExpression=Attr('s3_url').eq(s3_url))
        items = resp.get('Items', [])
        if items:
            return respond(200, {'exists': True, 'duplicate': False,
                                 's3_url': items[0].get('s3_url', '')})

    return respond(200, {'exists': False, 'duplicate': False})


def handle_tags(body):
    requested_raw = body.get('tags', {})

    if isinstance(requested_raw, list):
        requested = {t.lower().strip(): 1 for t in requested_raw if t}
    elif isinstance(requested_raw, str):
        requested = {}
        for part in requested_raw.split(','):
            part = part.strip()
            if ':' in part:
                name, _, count = part.partition(':')
                requested[name.strip().lower()] = int(count.strip()) if count.strip().isdigit() else 1
            elif part:
                requested[part.lower()] = 1
    elif isinstance(requested_raw, dict):
        requested = {k.lower().strip(): int(v) for k, v in requested_raw.items() if k}
    else:
        requested = {}

    print(f"handle_tags — requested={requested}")

    all_items = scan_all()
    results = []

    for item in all_items:
        item_tags = clean_tags(item.get('tags', {}))

        if not requested:
            url = item.get('thumbnail_url') or item.get('s3_url', '')
            if url:
                results.append(url)
            continue

       
        try:
            match = all(
                item_tags.get(tag, Decimal('0')) >= Decimal(str(count))
                for tag, count in requested.items()
            )
            if match:
                url = item.get('thumbnail_url') or item.get('s3_url', '')
                if url:
                    results.append(url)
        except Exception as e:
            print(f"Tag match error for {item.get('File_id')}: {e}")

    print(f"handle_tags — {len(results)} results")
    return respond(200, {'results': results, 'count': len(results)})



def handle_thumbnail(body):
    thumb_url = body.get('thumbnail_url', '').strip()
    if not thumb_url:
        return respond(400, {'error': 'No thumbnail_url provided'})

    resp  = table.scan(FilterExpression=Attr('thumbnail_url').eq(thumb_url))
    items = resp.get('Items', [])
    if items:
        return respond(200, {'exists': True, 's3_url': items[0].get('s3_url', ''),
                             'tags': {k: str(v) for k, v in clean_tags(items[0].get('tags', {})).items()}})
    return respond(404, {'error': 'Thumbnail not found'})


def handle_query_file(body):
    file_base64 = body.get('file_base64', '')
    if not file_base64:
        return respond(400, {'error': 'No file_base64 provided'})

    try:
        content = base64.b64decode(file_base64)
    except Exception as e:
        return respond(400, {'error': f'Invalid base64: {e}'})

    checksum = hashlib.md5(content).hexdigest()
    print(f"query_file checksum: {checksum}")

   
    query_tags = None
    try:
        boundary = '----EcoLensBoundary7MA4YWxkTrZu0gW'
        ml_body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="query.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        ).encode() + content + f'\r\n--{boundary}--\r\n'.encode()

        req = urlreq.Request(
            EC2_ML_URL, data=ml_body,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
            method='POST'
        )
        with urlreq.urlopen(req, timeout=30) as r:
            ml_result = json.loads(r.read().decode())
            raw = ml_result.get('tags', ml_result.get('predictions', {}))
            query_tags = clean_tags(raw)
            print(f"query_file ML tags: {query_tags}")
    except Exception as e:
        print(f"ML API error, falling back to checksum: {e}")

    all_items = scan_all()
    results = []

    for item in all_items:
        if query_tags:
            item_tags = clean_tags(item.get('tags', {}))
            if all(item_tags.get(t, Decimal('0')) >= c for t, c in query_tags.items()):
                results.append(item.get('s3_url', ''))
        else:
           
            if item.get('checksum') == checksum:
                results.append(item.get('s3_url', ''))

    print(f"query_file — {len(results)} results")
    return respond(200, {'results': results, 'count': len(results),
                         'detected_tags': {k: str(v) for k, v in (query_tags or {}).items()}})



def handle_edit(body):
    urls      = body.get('urls', [])
    tags      = body.get('tags', [])
    operation = int(body.get('operation', 1))

    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',') if t.strip()]

    if not urls: return respond(400, {'error': 'No URLs provided'})
    if not tags: return respond(400, {'error': 'No tags provided'})

    updated, errors = 0, []

    for url in urls:
        url = url.strip()
        resp  = table.scan(FilterExpression=Attr('s3_url').eq(url))
        items = resp.get('Items', [])

        if not items:
            errors.append(f'Not found: {url}')
            continue

        for item in items:
            current_tags = clean_tags(item.get('tags', {}))

            if operation == 1:
                for tag in tags:
                    tag = tag.lower().strip()
                    current_tags[tag] = current_tags.get(tag, Decimal('0')) + Decimal('1')
            else:
                for tag in tags:
                    current_tags.pop(tag.lower().strip(), None)

            table.update_item(
                Key={'File_id': item['File_id']},
                UpdateExpression='SET tags = :t',
                ExpressionAttributeValues={':t': current_tags}
            )
            updated += 1

    msg = f'Tags {"added" if operation == 1 else "removed"} for {updated} file(s).'
    if errors:
        msg += f' Skipped: {len(errors)} not found.'
    return respond(200, {'message': msg, 'updated': updated, 'errors': errors})



def handle_delete(body):
    urls = body.get('urls', [])
    if not urls:
        return respond(400, {'error': 'No URLs provided'})

    deleted, errors = 0, []

    for url in urls:
        url   = url.strip()
        resp  = table.scan(FilterExpression=Attr('s3_url').eq(url))
        items = resp.get('Items', [])

        if not items:
            errors.append(f'Not found: {url}')
            continue

        for item in items:
         
            try:
                bucket = url.split('.s3.amazonaws.com')[0].replace('https://', '')
                key    = url.split('.amazonaws.com/')[-1]
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception as e:
                errors.append(f'S3 error: {e}')

            thumb_url = item.get('thumbnail_url', '')
            if thumb_url and thumb_url != url:
                try:
                    t_bucket = thumb_url.split('.s3.amazonaws.com')[0].replace('https://', '')
                    t_key    = thumb_url.split('.amazonaws.com/')[-1]
                    s3.delete_object(Bucket=t_bucket, Key=t_key)
                except Exception as e:
                    print(f"Thumbnail delete error: {e}")

            table.delete_item(Key={'File_id': item['File_id']})
            deleted += 1

    return respond(200, {'message': f'Deleted {deleted} file(s).', 'deleted': deleted, 'errors': errors})