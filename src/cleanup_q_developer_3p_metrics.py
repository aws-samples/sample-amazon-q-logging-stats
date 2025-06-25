#!/usr/bin/env python
"""
Amazon Q Developer 3P Integration - Cleanup Script

This script cleans up AWS resources created by the setup scripts:
1. Deletes CloudTrail trails
2. Empties and deletes S3 buckets
3. Deletes Lambda functions
4. Deletes IAM roles and policies
5. Deletes EventBridge rules and targets

Note: This does NOT clean up Amazon Q Developer configurations - those must be manually disabled.
"""

import argparse
import boto3
import json
import time
from botocore.exceptions import ClientError

class QDeveloper3PCleanup:
    def __init__(self, bucket_name, region='us-east-1'):
        """Initialize the cleanup with bucket name and region"""
        self.bucket_name = bucket_name
        self.region = region
        self.s3_client = boto3.client('s3', region_name=region)
        self.cloudtrail_client = boto3.client('cloudtrail', region_name=region)
        self.lambda_client = boto3.client('lambda', region_name=region)
        self.iam_client = boto3.client('iam')
        self.events_client = boto3.client('events', region_name=region)
        
        print(f"Initializing cleanup for region {region}")

    def delete_eventbridge_rules(self):
        """Delete EventBridge rules and targets"""
        rules_to_delete = [
            'QDeveloper3PSetupSchedule',
            'IAMIdentityCenterUserExtractSchedule'
        ]
        
        for rule_name in rules_to_delete:
            try:
                # First, remove all targets from the rule
                targets_response = self.events_client.list_targets_by_rule(Rule=rule_name)
                if targets_response.get('Targets'):
                    target_ids = [target['Id'] for target in targets_response['Targets']]
                    self.events_client.remove_targets(
                        Rule=rule_name,
                        Ids=target_ids
                    )
                    print(f"Removed targets from EventBridge rule: {rule_name}")
                
                # Then delete the rule
                self.events_client.delete_rule(Name=rule_name)
                print(f"Deleted EventBridge rule: {rule_name}")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print(f"EventBridge rule {rule_name} not found (already deleted)")
                else:
                    print(f"Error deleting EventBridge rule {rule_name}: {e}")

    def delete_lambda_functions(self):
        """Delete Lambda functions"""
        functions_to_delete = [
            'QDeveloper3PSetup',
            'IAMIdentityCenterUserExtract'
        ]
        
        for function_name in functions_to_delete:
            try:
                self.lambda_client.delete_function(FunctionName=function_name)
                print(f"Deleted Lambda function: {function_name}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print(f"Lambda function {function_name} not found (already deleted)")
                else:
                    print(f"Error deleting Lambda function {function_name}: {e}")

    def delete_iam_roles_and_policies(self):
        """Delete IAM roles and their attached policies"""
        roles_to_delete = [
            {
                'role_name': 'lambda-q-developer-role',
                'policy_name': 'QDeveloper3PPermissions'
            },
            {
                'role_name': 'lambda-iam-identity-center-extract-role',
                'policy_name': 'IAMIdentityCenterExtractPermissions'
            }
        ]
        
        for role_info in roles_to_delete:
            role_name = role_info['role_name']
            policy_name = role_info['policy_name']
            
            try:
                # First, delete the inline policy
                try:
                    self.iam_client.delete_role_policy(
                        RoleName=role_name,
                        PolicyName=policy_name
                    )
                    print(f"Deleted inline policy {policy_name} from role {role_name}")
                except ClientError as e:
                    if e.response['Error']['Code'] != 'NoSuchEntity':
                        print(f"Error deleting policy {policy_name}: {e}")
                
                # Then delete the role
                self.iam_client.delete_role(RoleName=role_name)
                print(f"Deleted IAM role: {role_name}")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    print(f"IAM role {role_name} not found (already deleted)")
                else:
                    print(f"Error deleting IAM role {role_name}: {e}")

    def delete_cloudtrail(self):
        """Delete CloudTrail trail"""
        trail_name = f"q-developer-3p-trail-{self.bucket_name}"
        
        try:
            self.cloudtrail_client.delete_trail(Name=trail_name)
            print(f"Deleted CloudTrail: {trail_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'TrailNotFoundException':
                print(f"CloudTrail {trail_name} not found (already deleted)")
            else:
                print(f"Error deleting CloudTrail {trail_name}: {e}")

    def empty_s3_bucket(self):
        """Empty S3 bucket by deleting all objects"""
        try:
            # Check if bucket exists
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            
            # List and delete all objects
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name)
            
            objects_deleted = 0
            for page in pages:
                if 'Contents' in page:
                    objects_to_delete = [{'Key': obj['Key']} for obj in page['Contents']]
                    if objects_to_delete:
                        self.s3_client.delete_objects(
                            Bucket=self.bucket_name,
                            Delete={'Objects': objects_to_delete}
                        )
                        objects_deleted += len(objects_to_delete)
            
            # List and delete all object versions (for versioned buckets)
            try:
                paginator = self.s3_client.get_paginator('list_object_versions')
                pages = paginator.paginate(Bucket=self.bucket_name)
                
                for page in pages:
                    versions_to_delete = []
                    if 'Versions' in page:
                        versions_to_delete.extend([
                            {'Key': obj['Key'], 'VersionId': obj['VersionId']} 
                            for obj in page['Versions']
                        ])
                    if 'DeleteMarkers' in page:
                        versions_to_delete.extend([
                            {'Key': obj['Key'], 'VersionId': obj['VersionId']} 
                            for obj in page['DeleteMarkers']
                        ])
                    
                    if versions_to_delete:
                        self.s3_client.delete_objects(
                            Bucket=self.bucket_name,
                            Delete={'Objects': versions_to_delete}
                        )
                        objects_deleted += len(versions_to_delete)
            except ClientError:
                # Bucket might not be versioned
                pass
            
            print(f"Emptied S3 bucket {self.bucket_name} ({objects_deleted} objects deleted)")
            
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                print(f"S3 bucket {self.bucket_name} not found (already deleted)")
            else:
                print(f"Error emptying S3 bucket {self.bucket_name}: {e}")

    def delete_s3_bucket(self):
        """Delete S3 bucket"""
        try:
            self.s3_client.delete_bucket(Bucket=self.bucket_name)
            print(f"Deleted S3 bucket: {self.bucket_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"S3 bucket {self.bucket_name} not found (already deleted)")
            else:
                print(f"Error deleting S3 bucket {self.bucket_name}: {e}")

    def run_cleanup(self):
        """Run the complete cleanup process"""
        print(f"Starting cleanup for Q Developer 3P integration...")
        print(f"Bucket: {self.bucket_name}")
        print(f"Region: {self.region}")
        print("-" * 50)
        
        # Delete EventBridge rules first (they reference Lambda functions)
        print("1. Deleting EventBridge rules...")
        self.delete_eventbridge_rules()
        
        # Delete Lambda functions
        print("\n2. Deleting Lambda functions...")
        self.delete_lambda_functions()
        
        # Delete IAM roles and policies
        print("\n3. Deleting IAM roles and policies...")
        self.delete_iam_roles_and_policies()
        
        # Delete CloudTrail
        print("\n4. Deleting CloudTrail...")
        self.delete_cloudtrail()
        
        # Empty and delete S3 bucket
        print("\n5. Emptying S3 bucket...")
        self.empty_s3_bucket()
        
        print("\n6. Deleting S3 bucket...")
        self.delete_s3_bucket()
        
        print("\n" + "=" * 50)
        print("Cleanup completed!")
        print("\nIMPORTANT: Manual steps required:")
        print("1. Go to Amazon Q Developer console")
        print("2. Disable prompt logging in Preferences")
        print("3. Disable 'Collect granular metrics per user' in usage activity")
        print("4. Remove S3 location configurations")

def main():
    parser = argparse.ArgumentParser(description='Clean up Q Developer 3P integration resources')
    parser.add_argument('--bucket-name', required=True, help='S3 bucket name to clean up')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--confirm', action='store_true', help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    if not args.confirm:
        print(f"This will delete the following resources:")
        print(f"- S3 bucket: {args.bucket_name} (and ALL its contents)")
        print(f"- CloudTrail: q-developer-3p-trail-{args.bucket_name}")
        print(f"- Lambda functions: QDeveloper3PSetup, IAMIdentityCenterUserExtract")
        print(f"- IAM roles: lambda-q-developer-role, lambda-iam-identity-center-extract-role")
        print(f"- EventBridge rules: QDeveloper3PSetupSchedule, IAMIdentityCenterUserExtractSchedule")
        print(f"- Region: {args.region}")
        print("\nThis action cannot be undone!")
        
        confirmation = input("\nAre you sure you want to proceed? (type 'yes' to confirm): ")
        if confirmation.lower() != 'yes':
            print("Cleanup cancelled.")
            return
    
    # Initialize and run cleanup
    cleanup = QDeveloper3PCleanup(args.bucket_name, args.region)
    cleanup.run_cleanup()

if __name__ == "__main__":
    main()
