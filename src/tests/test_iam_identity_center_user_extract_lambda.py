#!/usr/bin/env python3
"""
Unit tests for IAM Identity Center User Extraction Lambda Function
"""

import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
import json
import boto3
from botocore.exceptions import ClientError
import io

# Add parent directory to path to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from iam_identity_center_user_extract_lambda import IAMIdentityCenterUserExtractor, lambda_handler


class TestIAMIdentityCenterUserExtractLambda(unittest.TestCase):
    """Test cases for IAM Identity Center User Extract Lambda"""

    def setUp(self):
        """Set up test fixtures"""
        self.bucket_name = "test-bucket"
        self.region = "us-east-1"
        
        # Create patcher for boto3 clients
        self.mock_boto3 = patch('iam_identity_center_user_extract_lambda.boto3').start()
        
        # Set up mock clients
        self.mock_s3 = MagicMock()
        self.mock_sso_admin = MagicMock()
        self.mock_identity_store = MagicMock()
        
        # Configure boto3 client mocks
        self.mock_boto3.client.side_effect = self._mock_boto3_client
        
        # Create the extractor instance with mocked clients
        self.extractor = IAMIdentityCenterUserExtractor(self.bucket_name, self.region)
        
    def tearDown(self):
        """Tear down test fixtures"""
        patch.stopall()
        
    def _mock_boto3_client(self, service_name, **kwargs):
        """Return appropriate mock client based on service name"""
        if service_name == 's3':
            return self.mock_s3
        elif service_name == 'sso-admin':
            return self.mock_sso_admin
        elif service_name == 'identitystore':
            return self.mock_identity_store
        return MagicMock()
        
    def test_init(self):
        """Test initialization of IAMIdentityCenterUserExtractor"""
        self.assertEqual(self.extractor.bucket_name, self.bucket_name)
        self.assertEqual(self.extractor.region, self.region)
        
    def test_extract_users_success(self):
        """Test extract_users when successful"""
        # Mock SSO instance response
        self.mock_sso_admin.list_instances.return_value = {
            'Instances': [{
                'InstanceArn': 'arn:aws:sso:::instance/ssoins-12345',
                'IdentityStoreId': 'd-12345'
            }]
        }
        
        # Mock users response
        self.mock_identity_store.list_users.return_value = {
            'Users': [
                {
                    'UserId': 'user-1',
                    'UserName': 'testuser',
                    'Name': {'GivenName': 'Test', 'FamilyName': 'User'},
                    'Emails': [{'Value': 'test@example.com', 'Primary': True}]
                }
            ]
        }
        
        result = self.extractor.extract_users()
        
        self.assertTrue(result['success'])
        self.assertEqual(result['user_count'], 1)
        self.mock_sso_admin.list_instances.assert_called_once()
        self.mock_identity_store.list_users.assert_called_once_with(IdentityStoreId='d-12345')
        self.mock_s3.put_object.assert_called_once()
        
    def test_extract_users_no_instances(self):
        """Test extract_users when no SSO instances found"""
        # Mock empty SSO instance response
        self.mock_sso_admin.list_instances.return_value = {'Instances': []}
        
        result = self.extractor.extract_users()
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], 'No IAM Identity Center instances found')
        self.mock_sso_admin.list_instances.assert_called_once()
        self.mock_identity_store.list_users.assert_not_called()
        
    def test_extract_users_client_error(self):
        """Test extract_users when a ClientError occurs"""
        # Mock SSO instance to raise ClientError
        self.mock_sso_admin.list_instances.side_effect = ClientError(
            {'Error': {'Code': '500', 'Message': 'Internal Error'}},
            'ListInstances'
        )
        
        result = self.extractor.extract_users()
        
        self.assertFalse(result['success'])
        self.assertIn('Error exporting IAM Identity Center users', result['message'])
        self.mock_sso_admin.list_instances.assert_called_once()
        
    def test_extract_users_with_pagination(self):
        """Test extract_users with pagination"""
        # Mock SSO instance response
        self.mock_sso_admin.list_instances.return_value = {
            'Instances': [{
                'InstanceArn': 'arn:aws:sso:::instance/ssoins-12345',
                'IdentityStoreId': 'd-12345'
            }]
        }
        
        # Mock paginated users response
        self.mock_identity_store.list_users.side_effect = [
            {
                'Users': [
                    {
                        'UserId': 'user-1',
                        'UserName': 'testuser1',
                        'Name': {'GivenName': 'Test', 'FamilyName': 'User1'},
                        'Emails': [{'Value': 'test1@example.com', 'Primary': True}]
                    }
                ],
                'NextToken': 'token123'
            },
            {
                'Users': [
                    {
                        'UserId': 'user-2',
                        'UserName': 'testuser2',
                        'Name': {'GivenName': 'Test', 'FamilyName': 'User2'},
                        'Emails': [{'Value': 'test2@example.com', 'Primary': True}]
                    }
                ]
            }
        ]
        
        result = self.extractor.extract_users()
        
        self.assertTrue(result['success'])
        self.assertEqual(result['user_count'], 2)
        self.mock_identity_store.list_users.assert_has_calls([
            call(IdentityStoreId='d-12345'),
            call(IdentityStoreId='d-12345', NextToken='token123')
        ])
        
    def test_lambda_handler_success(self):
        """Test lambda_handler with successful execution"""
        event = {
            'bucket_name': 'test-bucket',
            'region': 'us-east-1',
            'output_file': 'test-users.csv'
        }
        context = {}
        
        with patch('iam_identity_center_user_extract_lambda.IAMIdentityCenterUserExtractor') as mock_extractor_class:
            mock_extractor = MagicMock()
            mock_extractor_class.return_value = mock_extractor
            mock_extractor.extract_users.return_value = {
                'success': True,
                'message': 'Successfully exported 10 users to S3',
                'user_count': 10
            }
            
            response = lambda_handler(event, context)
            
            self.assertEqual(response['statusCode'], 200)
            response_body = json.loads(response['body'])
            self.assertEqual(response_body['user_count'], 10)
            mock_extractor_class.assert_called_once_with('test-bucket', 'us-east-1')
            mock_extractor.extract_users.assert_called_once_with('test-users.csv')
            
    def test_lambda_handler_missing_bucket(self):
        """Test lambda_handler with missing bucket_name parameter"""
        event = {
            'region': 'us-east-1',
            'output_file': 'test-users.csv'
        }
        context = {}
        
        response = lambda_handler(event, context)
        
        self.assertEqual(response['statusCode'], 400)
        response_body = json.loads(response['body'])
        self.assertEqual(response_body['message'], 'Missing required parameter: bucket_name')
        
    def test_lambda_handler_failure(self):
        """Test lambda_handler with extraction failure"""
        event = {
            'bucket_name': 'test-bucket',
            'region': 'us-east-1'
        }
        context = {}
        
        with patch('iam_identity_center_user_extract_lambda.IAMIdentityCenterUserExtractor') as mock_extractor_class:
            mock_extractor = MagicMock()
            mock_extractor_class.return_value = mock_extractor
            mock_extractor.extract_users.return_value = {
                'success': False,
                'message': 'Error exporting users'
            }
            
            response = lambda_handler(event, context)
            
            self.assertEqual(response['statusCode'], 500)
            response_body = json.loads(response['body'])
            self.assertEqual(response_body['message'], 'Error exporting users')


if __name__ == '__main__':
    unittest.main()