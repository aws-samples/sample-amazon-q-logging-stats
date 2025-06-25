#!/usr/bin/env python3
"""
Unit tests for Amazon Q Developer Data Ingestion to 3P setup script
"""

import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
import json
import boto3
from botocore.exceptions import ClientError

# Add parent directory to path to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from setup_q_developer_3p_metrcis import QDeveloper3PSetup


class TestQDeveloper3PSetup(unittest.TestCase):
    """Test cases for QDeveloper3PSetup class"""

    def setUp(self):
        """Set up test fixtures"""
        self.bucket_name = "test-q-developer-bucket"
        self.region = "us-east-1"
        self.account_id = "123456789012"
        
        # Create patcher for boto3 clients
        self.mock_boto3 = patch('setup_q_developer_3p_metrcis.boto3').start()
        
        # Set up mock clients
        self.mock_s3 = MagicMock()
        self.mock_cloudtrail = MagicMock()
        self.mock_sso_admin = MagicMock()
        self.mock_identity_store = MagicMock()
        self.mock_sts = MagicMock()
        
        # Configure boto3 client mocks
        self.mock_boto3.client.side_effect = self._mock_boto3_client
        
        # Configure STS get_caller_identity
        self.mock_sts.get_caller_identity.return_value = {'Account': self.account_id}
        
        # Create the setup instance with mocked clients
        self.setup = QDeveloper3PSetup(self.bucket_name, self.region)
        
        # Mock input function
        self.mock_input = patch('builtins.input', return_value='').start()
        
    def tearDown(self):
        """Tear down test fixtures"""
        patch.stopall()
        
    def _mock_boto3_client(self, service_name, **kwargs):
        """Return appropriate mock client based on service name"""
        if service_name == 's3':
            return self.mock_s3
        elif service_name == 'cloudtrail':
            return self.mock_cloudtrail
        elif service_name == 'sso-admin':
            return self.mock_sso_admin
        elif service_name == 'identitystore':
            return self.mock_identity_store
        elif service_name == 'sts':
            return self.mock_sts
        return MagicMock()
        
    def test_init(self):
        """Test initialization of QDeveloper3PSetup"""
        self.assertEqual(self.setup.bucket_name, self.bucket_name)
        self.assertEqual(self.setup.region, self.region)
        self.assertEqual(self.setup.account_id, self.account_id)
        
    def test_create_s3_bucket_existing(self):
        """Test create_s3_bucket when bucket already exists"""
        # Mock head_bucket to indicate bucket exists
        self.mock_s3.head_bucket.return_value = {}
        
        result = self.setup.create_s3_bucket()
        
        self.assertTrue(result)
        self.mock_s3.head_bucket.assert_called_once_with(Bucket=self.bucket_name)
        self.mock_s3.create_bucket.assert_not_called()
        self.mock_s3.put_bucket_policy.assert_called_once()
        
    def test_create_s3_bucket_new_us_east_1(self):
        """Test create_s3_bucket when bucket doesn't exist in us-east-1"""
        # Mock head_bucket to raise 404 error
        error_response = {'Error': {'Code': '404'}}
        self.mock_s3.head_bucket.side_effect = ClientError(error_response, 'HeadBucket')
        
        result = self.setup.create_s3_bucket()
        
        self.assertTrue(result)
        self.mock_s3.head_bucket.assert_called_once_with(Bucket=self.bucket_name)
        self.mock_s3.create_bucket.assert_called_once_with(Bucket=self.bucket_name)
        self.mock_s3.put_bucket_policy.assert_called_once()
        
    def test_create_s3_bucket_new_other_region(self):
        """Test create_s3_bucket when bucket doesn't exist in non-us-east-1 region"""
        # Set region to non-us-east-1
        self.setup.region = "us-west-2"
        
        # Mock head_bucket to raise 404 error
        error_response = {'Error': {'Code': '404'}}
        self.mock_s3.head_bucket.side_effect = ClientError(error_response, 'HeadBucket')
        
        result = self.setup.create_s3_bucket()
        
        self.assertTrue(result)
        self.mock_s3.head_bucket.assert_called_once_with(Bucket=self.bucket_name)
        self.mock_s3.create_bucket.assert_called_once_with(
            Bucket=self.bucket_name,
            CreateBucketConfiguration={'LocationConstraint': 'us-west-2'}
        )
        self.mock_s3.put_bucket_policy.assert_called_once()
        
    def test_create_s3_bucket_error(self):
        """Test create_s3_bucket when an error occurs"""
        # Mock head_bucket to raise a non-404 error
        error_response = {'Error': {'Code': '403', 'Message': 'Access Denied'}}
        self.mock_s3.head_bucket.side_effect = ClientError(error_response, 'HeadBucket')
        
        result = self.setup.create_s3_bucket()
        
        self.assertFalse(result)
        self.mock_s3.head_bucket.assert_called_once_with(Bucket=self.bucket_name)
        self.mock_s3.create_bucket.assert_not_called()
        
    def test_display_q_developer_instructions(self):
        """Test display_q_developer_instructions"""
        with patch('builtins.print') as mock_print:
            result = self.setup.display_q_developer_instructions()
            
            self.assertTrue(result)
            self.mock_input.assert_called_once()
            # Verify print was called multiple times with instructions
            self.assertGreater(mock_print.call_count, 5)
            
    def test_setup_cloudtrail_new_trail(self):
        """Test setup_cloudtrail when trail doesn't exist"""
        # Mock describe_trails to return empty list
        self.mock_cloudtrail.describe_trails.return_value = {'trailList': []}
        
        result = self.setup.setup_cloudtrail()
        
        self.assertTrue(result)
        self.mock_cloudtrail.describe_trails.assert_called_once()
        self.mock_cloudtrail.create_trail.assert_called_once_with(
            Name="QDeveloper3PTrail",
            S3BucketName=self.bucket_name,
            S3KeyPrefix='cloudtrail',
            IsMultiRegionTrail=True,
            EnableLogFileValidation=True
        )
        self.mock_cloudtrail.put_event_selectors.assert_called_once()
        self.mock_cloudtrail.start_logging.assert_called_once_with(Name="QDeveloper3PTrail")
        
    def test_setup_cloudtrail_existing_trail(self):
        """Test setup_cloudtrail when trail already exists"""
        # Mock describe_trails to return existing trail
        self.mock_cloudtrail.describe_trails.return_value = {
            'trailList': [{'Name': 'QDeveloper3PTrail'}]
        }
        
        result = self.setup.setup_cloudtrail()
        
        self.assertTrue(result)
        self.mock_cloudtrail.describe_trails.assert_called_once()
        self.mock_cloudtrail.create_trail.assert_not_called()
        self.mock_cloudtrail.put_event_selectors.assert_called_once()
        self.mock_cloudtrail.start_logging.assert_called_once_with(Name="QDeveloper3PTrail")
        
    def test_setup_cloudtrail_error(self):
        """Test setup_cloudtrail when an error occurs"""
        # Mock describe_trails to raise an error
        self.mock_cloudtrail.describe_trails.side_effect = ClientError(
            {'Error': {'Code': '500', 'Message': 'Internal Error'}},
            'DescribeTrails'
        )
        
        result = self.setup.setup_cloudtrail()
        
        self.assertFalse(result)
        self.mock_cloudtrail.describe_trails.assert_called_once()
        self.mock_cloudtrail.create_trail.assert_not_called()
        
    def test_export_identity_center_users_success(self):
        """Test export_identity_center_users when successful"""
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
        
        # Mock file operations
        with patch('builtins.open', create=True) as mock_open, \
             patch('os.remove') as mock_remove:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file
            
            result = self.setup.export_identity_center_users()
            
            self.assertTrue(result)
            self.mock_sso_admin.list_instances.assert_called_once()
            self.mock_identity_store.list_users.assert_called_once_with(IdentityStoreId='d-12345')
            self.mock_s3.upload_file.assert_called_once()
            mock_remove.assert_called_once()
            
    def test_export_identity_center_users_no_instances(self):
        """Test export_identity_center_users when no SSO instances found"""
        # Mock empty SSO instance response
        self.mock_sso_admin.list_instances.return_value = {'Instances': []}
        
        result = self.setup.export_identity_center_users()
        
        self.assertFalse(result)
        self.mock_sso_admin.list_instances.assert_called_once()
        self.mock_identity_store.list_users.assert_not_called()
        
    def test_run_setup_success(self):
        """Test run_setup when all steps succeed"""
        # Mock all the individual methods
        with patch.object(self.setup, 'create_s3_bucket', return_value=True) as mock_create_bucket, \
             patch.object(self.setup, 'display_q_developer_instructions', return_value=True) as mock_display, \
             patch.object(self.setup, 'setup_cloudtrail', return_value=True) as mock_setup_cloudtrail, \
             patch.object(self.setup, 'export_identity_center_users', return_value=True) as mock_export_users:
            
            result = self.setup.run_setup(export_users=True)
            
            self.assertTrue(result)
            mock_create_bucket.assert_called_once()
            mock_display.assert_called_once()
            mock_setup_cloudtrail.assert_called_once()
            mock_export_users.assert_called_once_with('users.csv')
            
    def test_run_setup_bucket_failure(self):
        """Test run_setup when bucket creation fails"""
        # Mock bucket creation to fail
        with patch.object(self.setup, 'create_s3_bucket', return_value=False) as mock_create_bucket, \
             patch.object(self.setup, 'display_q_developer_instructions') as mock_display, \
             patch.object(self.setup, 'setup_cloudtrail') as mock_setup_cloudtrail, \
             patch.object(self.setup, 'export_identity_center_users') as mock_export_users:
            
            result = self.setup.run_setup()
            
            self.assertFalse(result)
            mock_create_bucket.assert_called_once()
            mock_display.assert_not_called()
            mock_setup_cloudtrail.assert_not_called()
            mock_export_users.assert_not_called()
            
    def test_run_setup_cloudtrail_failure(self):
        """Test run_setup when CloudTrail setup fails"""
        # Mock CloudTrail setup to fail
        with patch.object(self.setup, 'create_s3_bucket', return_value=True) as mock_create_bucket, \
             patch.object(self.setup, 'display_q_developer_instructions', return_value=True) as mock_display, \
             patch.object(self.setup, 'setup_cloudtrail', return_value=False) as mock_setup_cloudtrail, \
             patch.object(self.setup, 'export_identity_center_users') as mock_export_users:
            
            result = self.setup.run_setup()
            
            self.assertFalse(result)
            mock_create_bucket.assert_called_once()
            mock_display.assert_called_once()
            mock_setup_cloudtrail.assert_called_once()
            mock_export_users.assert_not_called()


if __name__ == '__main__':
    unittest.main()
