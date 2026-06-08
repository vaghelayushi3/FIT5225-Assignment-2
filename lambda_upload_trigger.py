import json
import boto3
import hashlib
import urllib.parse
from boto3.dynamodb.conditions import Attr
from decimal import Decimal
import re
import io
import urllib.request as urlreq
import os

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('MediaFiles')
sns = boto3.client('sns')

SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:595165123434:ecolence-notifications'
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
    """
    Normalises any tag format → {clean_name: Decimal(count)}
    Only keeps count > 0. Strips UUID/taxonomy keys.
    """
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



def get_ml_tags(image_bytes, filename):
    try:
        rekognition = boto3.client('rekognition', region_name='us-east-1')
        response = rekognition.detect_labels(
            Image={'Bytes': image_bytes},
            MaxLabels=10,
            MinConfidence=50
        )
        tags = {}
        
        label_map = {
            'Cattle': 'cattle', 'Cow': 'cattle', 'Bull': 'cattle',
            'Pig': 'wild boar', 'Boar': 'wild boar', 'Hog': 'wild boar',
            'Kangaroo': 'kangaroo', 'Koala': 'koala',
            'Bird': 'australian brushturkey', 'Turkey': 'australian brushturkey',
            'Dog': 'dingo', 'Wolf': 'dingo',
            'Deer': 'swamp wallaby', 'Wallaby': 'swamp wallaby',
            'Snake': 'snake', 'Reptile': 'snake',
            'Horse': 'horse', 'Wildlife': 'wildlife',
            'Animal': 'animal', 'Mammal': 'cattle'
        }
        for label in response['Labels']:
            name = label['Name']
            confidence = label['Confidence']
            if name in label_map:
                clean = label_map[name]
                tags[clean] = tags.get(clean, 0) + 1
                print(f"Rekognition: {name} ({confidence:.1f}%) → {clean}")
       
        if not tags and response['Labels']:
            top = response['Labels'][0]['Name'].lower().replace(' ', '_')
            tags[top] = 1
        print(f"Final Rekognition tags: {tags}")
        return tags
    except Exception as e:
        print(f"Rekognition failed: {e}")
        return {}



def create_thumbnail(content, bucket, file_id):
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        w, h = img.size
        new_w = 200
        new_h = int(h * new_w / w)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=60)
        buffer.seek(0)
        thumb_key = f"thumbnails/{file_id}.jpg"
        s3.put_object(Bucket=bucket, Key=thumb_key, Body=buffer.getvalue(), ContentType='image/jpeg')
        url = f"https://{bucket}.s3.amazonaws.com/{thumb_key}"
        print(f"Thumbnail: {url}")
        return url
    except ImportError:
        print("PIL not available — add Pillow Lambda Layer")
        return None
    except Exception as e:
        print(f"Thumbnail failed (non-critical): {e}")
        return None



def extract_video_frames(content, filename):
    try:
        import cv2
        tmp_path = f'/tmp/{filename}'
        with open(tmp_path, 'wb') as f:
            f.write(content)
        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 1
        frames = []
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % int(fps) == 0:
                _, buf = cv2.imencode('.jpg', frame)
                frames.append(buf.tobytes())
            frame_count += 1
        cap.release()
        try:
            os.remove(tmp_path)
        except:
            pass
        print(f"Extracted {len(frames)} frames")
        return frames
    except ImportError:
        print("OpenCV not available")
        return []
    except Exception as e:
        print(f"Video extraction failed: {e}")
        return []




def lambda_handler(event, context):
    try:
        print(f"Event: {json.dumps(event)}")

        bucket = event['Records'][0]['s3']['bucket']['name']
        key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'])
        print(f"Processing: s3://{bucket}/{key}")

    
        if key.startswith('thumbnails/'):
            print("Skipping thumbnail")
            return {'statusCode': 200, 'body': 'Skipped thumbnail'}

      
        response = s3.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
        if not content:
            return {'statusCode': 400, 'body': 'Empty file'}
        print(f"File size: {len(content)} bytes")

  
        checksum = hashlib.md5(content).hexdigest()
        print(f"Checksum: {checksum}")
        existing = table.scan(FilterExpression=Attr('checksum').eq(checksum))
        if existing.get('Count', 0) > 0:
            print("Duplicate — skipping")
            return {'statusCode': 200, 'body': 'Duplicate'}

      
        filename = key.split('/')[-1]
        file_ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
        IMAGE_TYPES = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'}
        VIDEO_TYPES = {'mp4', 'mov', 'avi', 'mkv', 'webm', 'flv'}
        is_image = file_ext in IMAGE_TYPES
        is_video = file_ext in VIDEO_TYPES
        file_type = 'image' if is_image else ('video' if is_video else file_ext)

        s3_url = f"https://{bucket}.s3.amazonaws.com/{key}"
        file_id = checksum

     
        thumbnail_url = s3_url
        if is_image:
            thumb = create_thumbnail(content, bucket, file_id)
            if thumb:
                thumbnail_url = thumb

        tags = {}
        if is_image:
            tags = get_ml_tags(content, filename)
        elif is_video:
            frames = extract_video_frames(content, filename)
            merged = {}
            for i, frame_bytes in enumerate(frames):
                frame_tags = get_ml_tags(frame_bytes, f"frame_{i}.jpg")
                for tag, count in frame_tags.items():
                    merged[tag] = max(merged.get(tag, Decimal('0')), count)
            tags = merged

        print(f"Final tags going to DynamoDB: {tags}")

        
        item = {
            'File_id': file_id,
            'checksum': checksum,
            's3_url': s3_url,
            'thumbnail_url': thumbnail_url,
            'file_type': file_type,
            'filename': filename,
            'tags': tags,
            'bucket': bucket,
            'key': key
        }
        table.put_item(Item=item)
        print(f"DynamoDB write SUCCESS — File_id: {file_id}, tags: {tags}")

    
        tag_str = ', '.join(f"{k}:{v}" for k, v in tags.items()) if tags else 'None detected'
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject='New Wildlife Media — Aussie EcoLens',
                Message=f"File: {filename}\nType: {file_type}\nURL: {s3_url}\nThumbnail: {thumbnail_url}\nTags: {tag_str}"
            )
        except Exception as e:
            print(f"SNS failed (non-critical): {e}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Success',
                'File_id': file_id,
                'tags': {k: str(v) for k, v in tags.items()},
                's3_url': s3_url,
                'thumbnail_url': thumbnail_url
            })
        }

    except KeyError as e:
        print(f"Event parse error: {e}")
        return {'statusCode': 400, 'body': f'Bad event: {str(e)}'}
    except Exception as e:
        import traceback
        print(f"FATAL: {traceback.format_exc()}")
        raise e