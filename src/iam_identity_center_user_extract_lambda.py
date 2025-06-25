"""
IAM Identity Center User Extraction - Lambda Function

This Lambda function extracts users from AWS IAM Identity Center and uploads the data to an S3 bucket:
1. Connects to IAM Identity Center
2. Extracts user information
3. Saves it to a CSV file
4. Uploads the CSV file to the specified S3 bucket

The function can be triggered on a schedule or manually invoked.

Required IAM Permissions for Lambda Execution Role:
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "sso-admin:ListInstances",
                "identitystore:ListUsers",
                "identitystore:DescribeUser"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        }
    ]
}
"""

import json
import csv
import io
import boto3
from botocore.exceptions import ClientError  

def lambda_handler(event, context):
    """
    Lambda handler function that extracts users from IAM Identity Center
    
    Parameters:
    - event: Contains input parameters like bucket_name, region, and output_file
    - context: Lambda execution context
    
    Returns:
    - JSON response with extraction results
    """
    # Extract parameters from the event
    bucket_name = event.get('bucket_name')
    region = event.get('region', 'us-east-1')
    output_file = event.get('output_file', 'users.csv')
    
    # Validate required parameters
    if not bucket_name:
        return {
            'statusCode': 400,
            'body': json.dumps({
                'message': 'Missing required parameter: bucket_name'
            })
        }
    
    # Initialize extractor
    extractor = IAMIdentityCenterUserExtractor(bucket_name, region)
    
    # Run extraction process
    result = extractor.extract_users(output_file)
    
    return {
        'statusCode': 200 if result['success'] else 500,
        'body': json.dumps({
            'message': result['message'],
            'bucket_name': bucket_name,
            'region': region,
            'output_file': output_file,
            'user_count': result.get('user_count', 0)
        })
    }

class IAMIdentityCenterUserExtractor:
    def __init__(self, bucket_name, region='us-east-1'):
        """Initialize the extractor with bucket name and region"""
        self.bucket_name = bucket_name
        self.region = region
        self.s3_client = boto3.client('s3', region_name=region)
        self.sso_admin_client = boto3.client('sso-admin', region_name=region)
        self.identity_store_client = boto3.client('identitystore', region_name=region)
        
        print(f"Initializing IAM Identity Center User Extractor in {region}")

    def extract_users(self, output_file="users.csv"):
        """Extract users from AWS IAM Identity Center and upload to S3"""
        try:
            # Get SSO instance using sso-admin client
            instances = self.sso_admin_client.list_instances()
            if not instances.get('Instances'):
                print("No IAM Identity Center instances found")
                return {
                    'success': False,
                    'message': 'No IAM Identity Center instances found'
                }
            
            instance_arn = instances['Instances'][0]['InstanceArn']
            identity_store_id = instances['Instances'][0]['IdentityStoreId']
            
            print(f"Found IAM Identity Center instance: {instance_arn}")
            print(f"Identity Store ID: {identity_store_id}")
            
            # List users
            users = []
            next_token = None
            
            while True:
                if next_token:
                    response = self.identity_store_client.list_users(
                        IdentityStoreId=identity_store_id,
                        NextToken=next_token
                    )
                else:
                    response = self.identity_store_client.list_users(
                        IdentityStoreId=identity_store_id
                    )
                
                users.extend(response.get('Users', []))
                next_token = response.get('NextToken')
                
                if not next_token:
                    break
            
            # Create CSV in memory (Lambda doesn't have persistent file system access)
            csv_buffer = io.StringIO()
            fieldnames = ['UserId', 'Username', 'Email', 'GivenName', 'FamilyName']
            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()
            
            for user in users:
                email = next((e['Value'] for e in user.get('Emails', []) if e.get('Primary', False)), '')
                writer.writerow({
                    'UserId': user.get('UserId', ''),
                    'Username': user.get('UserName', ''),
                    'Email': email,
                    'GivenName': user.get('Name', {}).get('GivenName', ''),
                    'FamilyName': user.get('Name', {}).get('FamilyName', '')
                })
            
            # Upload the CSV data to S3
            s3_key = f"users/{output_file}"
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=csv_buffer.getvalue()
            )
            
            print(f"Exported {len(users)} users to s3://{self.bucket_name}/{s3_key}")
            return {
                'success': True,
                'message': f'Successfully exported {len(users)} users to S3',
                'user_count': len(users)
            }
            
        except ClientError as e:
            error_message = f"Error exporting IAM Identity Center users: {e}"
            print(error_message)
            return {
                'success': False,
                'message': error_message
            }
        except Exception as e:
            error_message = f"Unexpected error exporting users: {e}"
            print(error_message)
            return {
                'success': False,
                'message': error_message
            }