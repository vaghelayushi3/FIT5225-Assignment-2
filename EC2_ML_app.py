from flask import Flask, request, jsonify
import torch
import io
import re
import os
import numpy as np
from PIL import Image

app = Flask(__name__)

MODEL_PATH = '/home/ubuntu/model.pt'
LABELS_PATH = '/home/ubuntu/labels.txt'
model = None
class_names = []

def load_class_names():
    global class_names
    lines = [l.strip().split(';')[-1].strip() for l in open(LABELS_PATH) if l.strip()]
    class_names = lines
    print(f"Loaded {len(class_names)} labels: {class_names[:3]}")

def load_model():
    global model
    load_class_names()
    print("Loading model...")
    model = torch.load(MODEL_PATH, map_location='cpu', weights_only=False)
    model.eval()
    print(f"Model loaded! Classes: {len(class_names)}")

def predict_image(image_bytes):
    try:
        import torchvision.transforms as transforms
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        transform = transforms.Compose([
            transforms.Resize((480, 480)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        tensor = transform(img).unsqueeze(0).permute(0,2,3,1)
        with torch.no_grad():
            outputs = model(tensor)
        probs = torch.softmax(outputs, dim=1)[0].cpu().numpy()
        top3_idx = np.argsort(probs)[::-1][:3]
        tags = {}
        for idx in top3_idx:
            if idx < len(class_names):
                name = class_names[idx].strip().lower()
                if len(name) >= 2:
                    tags[name] = int(tags.get(name, 0)) + 1
        print(f"Tags: {tags}")
        return tags
    except Exception as e:
        import traceback
        print(f"Predict error: {traceback.format_exc()}")
        return {}

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'model_loaded': model is not None, 'num_classes': len(class_names)})

@app.route('/predict', methods=['POST'])
def predict():
    try:
        image_bytes = None
        content_type = request.content_type or ''
        if 'multipart/form-data' in content_type:
            if 'image' not in request.files:
                return jsonify({'error': 'No image field'}), 400
            image_bytes = request.files['image'].read()
        elif 'application/json' in content_type:
            import base64
            data = request.get_json()
            b64 = data.get('file_base64', '')
            if b64:
                image_bytes = base64.b64decode(b64)
        else:
            image_bytes = request.get_data()
        if not image_bytes:
            return jsonify({'error': 'No image data'}), 400
        print(f"Received: {len(image_bytes)} bytes")
        tags = predict_image(image_bytes)
        return jsonify({'tags': tags, 'count': len(tags)})
    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500