# Aussie EcoLens - FIT5225 Assignment 2

A multi-cloud serverless wildlife observation platform that automatically detects and tags Australian wildlife species in uploaded media files.

## Team
- Ayushi Vaghela - 35469978 - Backend, AWS Infrastructure, ML Integration
- Jiayu Liu - 35821442 - Frontend UI, Architecture Diagram

## Architecture
- Frontend:React SPA with AWS Cognito authentication
- Backend: AWS Lambda, API Gateway, S3, DynamoDB, SNS
- ML: PyTorch model on EC2 + AWS Rekognition as fallback6
- Database: Amazon DynamoDB
- Storage: Amazon S3
- Auth: Amazon Cognito
- Notifications Amazon SNS

## Features
- User authentication with email verification (Cognito)
- Wildlife image upload with automatic species detection
- Duplicate file detection via MD5 checksum
- Thumbnail generation for uploaded images
- Video frame extraction at 1fps for species detection
- Query files by species tags with minimum counts
- Find matching files by uploading a sample image
- Manual tag add/remove in bulk
- File deletion from storage and database
- Email notifications on new uploads via SNS

## AWS Services Used
| Service | Purpose |
| Amazon Cognito | User authentication and authorisation |
| Amazon S3 | Media file and thumbnail storage |
| AWS Lambda | Serverless compute functions |
| Amazon API Gateway | REST API endpoints |
| Amazon DynamoDB | Metadata and tag storage |	
| Amazon SNS | Email notification service |
| AWS EC2 | ML model inference server |

## Repository Structure
aussie-ecolens/
-src/ app.js #React Frontend
 /index.js #React entry point
-public/
Index.html 
--lambda_upload_trigger.py # S3 upload trigger Lambda
--lambda_query_handler.py # Query and data management Lambda
--lambda_presigned_url.py # S3 presigned URL generator Lambda
--ec2_app.py # Flask ML API on EC2
-README.md


