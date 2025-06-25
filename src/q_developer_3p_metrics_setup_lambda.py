"""
Amazon Q Developer Data Ingestion to 3P - Lambda Function

This Lambda function automates the setup process for Amazon Q Developer data ingestion to 3P:
1. Creates an S3 bucket with required permissions for both Amazon Q and CloudTrail
2. Sets up CloudTrail with necessary configuration
3. Exports users from AWS IAM Identity Center (optional)

The function can be triggered on a schedule or manually invoked.

Required IAM Permissions for Lambda Execution Role:
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:CreateBucket",
                "s3:PutBucketPolicy",
                "s3:GetBucketPolicy",
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:HeadBucket"
            ],
            "Resource": [
                "arn:aws:s3:::*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "cloudtrail:CreateTrail",
                "cloudtrail:UpdateTrail",
                "cloudtrail:StartLogging",
                "cloudtrail:DescribeTrails",
                "cloudtrail:PutEventSelectors"
            ],
            "Resource": "*"
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
                "sts:GetCallerIdentity"
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
import time
import os
from botocore.exceptions import ClientError
import boto3


def lambda_handler(event, context):
    """
    Lambda handler function that processes the setup for Amazon Q Developer data ingestion to 3P
    
    Parameters:
    - event: Contains input parameters like bucket_name, region, and export_users flag
    - context: Lambda execution context
    
    Returns:
    - JSON response with setup results
    """
    # Extract parameters from the event
    bucket_name = event.get('bucket_name')
    region = event.get('region', 'us-east-1')
    export_users = event.get('export_users', False)
    output_file = event.get('output_file', 'users.csv')
    
    # Validate required parameters
    if not bucket_name:
        return {
            'statusCode': 400,
            'body': json.dumps({
                'message': 'Missing required parameter: bucket_name'
            })
        }
    
    # Initialize setup handler
    setup = QDeveloper3PSetup(bucket_name, region)
    
    # Run setup process
    result = setup.run_setup(export_users, output_file)
    
    return {
        'statusCode': 200 if result else 500,
        'body': json.dumps({
            'message': 'Setup completed successfully' if result else 'Setup failed',
            'bucket_name': bucket_name,
            'region': region,
            'export_users': export_users,
            'output_file': output_file if export_users else None
        })
    }

class QDeveloper3PSetup:
    def __init__(self, bucket_name, region='us-east-1'):
        """Initialize the setup with bucket name and region"""
        self.bucket_name = bucket_name
        self.region = region
        self.s3_client = boto3.client('s3', region_name=region)
        self.cloudtrail_client = boto3.client('cloudtrail', region_name=region)
        self.sso_admin_client = boto3.client('sso-admin', region_name=region)
        self.identity_store_client = boto3.client('identitystore', region_name=region)
        self.account_id = boto3.client('sts').get_caller_identity().get('Account')
        
        print(f"Initializing Amazon Q Developer to 3P setup in {region}")

    def create_s3_bucket(self):
        """Create S3 bucket with required permissions for both Amazon Q and CloudTrail"""
        try:
            # Check if bucket exists
            try:
                self.s3_client.head_bucket(Bucket=self.bucket_name)
                print(f"Bucket {self.bucket_name} already exists")
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    # Create bucket
                    if self.region == 'us-east-1':
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={'LocationConstraint': self.region}
                        )
                    print(f"Created bucket: {self.bucket_name}")
                else:
                    raise

            # Set bucket policy with permissions for both Amazon Q and CloudTrail
            bucket_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowAmazonQAccess",
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "q.amazonaws.com"
                        },
                        "Action": [
                            "s3:GetObject",
                            "s3:ListBucket",
                            "s3:PutObject"
                        ],
                        "Resource": [
                            f"arn:aws:s3:::{self.bucket_name}",
                            f"arn:aws:s3:::{self.bucket_name}/*"
                        ]
                    },
                    {
                        "Sid": "AWSCloudTrailAclCheck",
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "cloudtrail.amazonaws.com"
                        },
                        "Action": "s3:GetBucketAcl",
                        "Resource": f"arn:aws:s3:::{self.bucket_name}"
                    },
                    {
                        "Sid": "AWSCloudTrailWrite",
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "cloudtrail.amazonaws.com"
                        },
                        "Action": "s3:PutObject",
                        "Resource": f"arn:aws:s3:::{self.bucket_name}/cloudtrail/*",
                        "Condition": {
                            "StringEquals": {
                                "s3:x-amz-acl": "bucket-owner-full-control"
                            }
                        }
                    }
                ]
            }
            
            self.s3_client.put_bucket_policy(
                Bucket=self.bucket_name,
                Policy=json.dumps(bucket_policy)
            )
            print(f"Updated bucket policy for {self.bucket_name} with Amazon Q and CloudTrail permissions")
            return True
            
        except ClientError as e:
            print(f"Error creating S3 bucket: {e}")
            return False

    def setup_cloudtrail(self, trail_name="QDeveloper3PTrail"):
        """Setup CloudTrail with required configuration"""
        try:
            # Check if trail exists
            trails = self.cloudtrail_client.describe_trails()
            trail_exists = False
            
            for trail in trails.get('trailList', []):
                if trail.get('Name') == trail_name:
                    trail_exists = True
                    break
            
            if not trail_exists:
                # Create trail
                self.cloudtrail_client.create_trail(
                    Name=trail_name,
                    S3BucketName=self.bucket_name,
                    S3KeyPrefix='cloudtrail',
                    IsMultiRegionTrail=True,
                    EnableLogFileValidation=True
                )
                print(f"Created CloudTrail trail: {trail_name}")
            else:
                print(f"CloudTrail trail {trail_name} already exists")
            
            # Enable data events for CodeWhisperer, Q Developer Integration, CodeWhisperer Customization
            advanced_event_selectors = [
                {
                    'Name': 'Log CodeWhisperer events',
                    'FieldSelectors': [
                        {
                            'Field': 'eventCategory',
                            'Equals': ['Data']
                        },
                        {
                            'Field': 'resources.type',
                            'Equals': ['AWS::CodeWhisperer::Profile']
                        }
                    ]
                },
                {
                    'Name': 'Log Q Developer Integration events',
                    'FieldSelectors': [
                        {
                            'Field': 'eventCategory',
                            'Equals': ['Data']
                        },
                        {
                            'Field': 'resources.type',
                            'Equals': ['AWS::QDeveloper::Integration']
                        }
                    ]
                },
                {
                    'Name': 'Log CodeWhisperer Customization events',
                    'FieldSelectors': [
                        {
                            'Field': 'eventCategory',
                            'Equals': ['Data']
                        },
                        {
                            'Field': 'resources.type',
                            'Equals': ['AWS::CodeWhisperer::Customization']
                        }
                    ]
                }
            ]
            
            self.cloudtrail_client.put_event_selectors(
                TrailName=trail_name,
                AdvancedEventSelectors=advanced_event_selectors
            )
            print(f"Configured data events for CloudTrail trail: {trail_name}")
            
            # Start logging
            self.cloudtrail_client.start_logging(Name=trail_name)
            print(f"Started logging for CloudTrail trail: {trail_name}")
            return True
            
        except ClientError as e:
            print(f"Error setting up CloudTrail: {e}")
            return False

    def export_identity_center_users(self, output_file="users.csv"):
        """Export users from AWS IAM Identity Center and upload to S3"""
        try:
            # Get SSO instance using sso-admin client
            instances = self.sso_admin_client.list_instances()
            if not instances.get('Instances'):
                print("No IAM Identity Center instances found")
                return False
            
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
            return True
            
        except ClientError as e:
            print(f"Error exporting IAM Identity Center users: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error exporting users: {e}")
            return False

    def run_setup(self, export_users=True, output_file="users.csv"):
        """Run the complete setup process"""
        print("Starting Amazon Q Developer to 3P setup...")
        
        # Step 1: Create S3 bucket with proper permissions
        if not self.create_s3_bucket():
            print("Failed to create S3 bucket. Aborting setup.")
            return False
        
        # Step 2: Setup CloudTrail
        if not self.setup_cloudtrail():
            print("Failed to setup CloudTrail. Aborting setup.")
            return False
        
        # Step 3: Export users from IAM Identity Center (optional)
        if export_users:
            if not self.export_identity_center_users(output_file):
                print("Failed to export IAM Identity Center users.")
                # Continue anyway as this is optional
        
        print("\nSetup completed successfully!")
        print(f"S3 bucket '{self.bucket_name}' is configured for Amazon Q Developer data ingestion")
        print(f"CloudTrail is configured to log Q Developer events to '{self.bucket_name}/cloudtrail/'")
        if export_users:
            print(f"IAM Identity Center users exported to s3://{self.bucket_name}/users/{output_file}")
        
        return True
