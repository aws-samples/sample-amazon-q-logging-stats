#!/usr/bin/env python3
"""
Unit tests for Q Developer 3P Cleanup Script
"""

import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
from botocore.exceptions import ClientError

# Add parent directory to path to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanup_q_developer_3p_metrics import QDeveloper3PCleanup


class TestQDeveloper3PCleanup(unittest.TestCase):
    """Test cases for QDeveloper3PCleanup class"""

    def setUp(self):
        """Set up test fixtures"""
        self.bucket_name = "test-cleanup-bucket"
        self.region = "us-east-1"
        
        # Create patcher for boto3 clients
        self.mock_boto3 = patch('cleanup_q_developer_3p_metrics.boto3').start()
        
        # Set up mock clients
        self.mock_s3 = MagicMock()
        self.mock_cloudtrail = MagicMock()
        self.mock_lambda = MagicMock()
        self.mock_iam = MagicMock()
        self.mock_events = MagicMock()
        
        # Configure boto3 client mocks
        self.mock_boto3.client.side_effect = self._mock_boto3_client
        
        # Create the cleanup instance with mocked clients
        self.cleanup = QDeveloper3PCleanup(self.bucket_name, self.region)
        
    def tearDown(self):
        """Tear down test fixtures"""
        patch.stopall()
        
    def _mock_boto3_client(self, service_name, **kwargs):
        """Return appropriate mock client based on service name"""
        if service_name == 's3':
            return self.mock_s3
        elif service_name == 'cloudtrail':
            return self.mock_cloudtrail
        elif service_name == 'lambda':
            return self.mock_lambda
        elif service_name == 'iam':
            return self.mock_iam
        elif service_name == 'events':
            return self.mock_events
        return MagicMock()

    def test_init(self):
        """Test cleanup initialization"""
        self.assertEqual(self.cleanup.bucket_name, self.bucket_name)
        self.assertEqual(self.cleanup.region, self.region)

    def test_delete_eventbridge_rules_success(self):
        """Test successful EventBridge rules deletion"""
        # Mock list_targets_by_rule response
        self.mock_events.list_targets_by_rule.return_value = {
            'Targets': [{'Id': '1'}, {'Id': '2'}]
        }
        
        self.cleanup.delete_eventbridge_rules()
        
        # Verify calls for both rules
        expected_calls = [
            call(Rule='QDeveloper3PSetupSchedule'),
            call(Rule='IAMIdentityCenterUserExtractSchedule')
        ]
        self.mock_events.list_targets_by_rule.assert_has_calls(expected_calls, any_order=True)
        
        # Verify remove_targets calls
        expected_remove_calls = [
            call(Rule='QDeveloper3PSetupSchedule', Ids=['1', '2']),
            call(Rule='IAMIdentityCenterUserExtractSchedule', Ids=['1', '2'])
        ]
        self.mock_events.remove_targets.assert_has_calls(expected_remove_calls, any_order=True)
        
        # Verify delete_rule calls
        expected_delete_calls = [
            call(Name='QDeveloper3PSetupSchedule'),
            call(Name='IAMIdentityCenterUserExtractSchedule')
        ]
        self.mock_events.delete_rule.assert_has_calls(expected_delete_calls, any_order=True)

    def test_delete_eventbridge_rules_not_found(self):
        """Test EventBridge rules deletion when rules don't exist"""
        # Mock ResourceNotFoundException
        self.mock_events.list_targets_by_rule.side_effect = ClientError(
            {'Error': {'Code': 'ResourceNotFoundException'}}, 'list_targets_by_rule'
        )
        
        # Should not raise exception
        self.cleanup.delete_eventbridge_rules()

    def test_delete_lambda_functions_success(self):
        """Test successful Lambda functions deletion"""
        self.cleanup.delete_lambda_functions()
        
        expected_calls = [
            call(FunctionName='QDeveloper3PSetup'),
            call(FunctionName='IAMIdentityCenterUserExtract')
        ]
        self.mock_lambda.delete_function.assert_has_calls(expected_calls, any_order=True)

    def test_delete_lambda_functions_not_found(self):
        """Test Lambda functions deletion when functions don't exist"""
        self.mock_lambda.delete_function.side_effect = ClientError(
            {'Error': {'Code': 'ResourceNotFoundException'}}, 'delete_function'
        )
        
        # Should not raise exception
        self.cleanup.delete_lambda_functions()

    def test_delete_iam_roles_success(self):
        """Test successful IAM roles and policies deletion"""
        self.cleanup.delete_iam_roles_and_policies()
        
        # Verify policy deletions
        expected_policy_calls = [
            call(RoleName='lambda-q-developer-role', PolicyName='QDeveloper3PPermissions'),
            call(RoleName='lambda-iam-identity-center-extract-role', PolicyName='IAMIdentityCenterExtractPermissions')
        ]
        self.mock_iam.delete_role_policy.assert_has_calls(expected_policy_calls, any_order=True)
        
        # Verify role deletions
        expected_role_calls = [
            call(RoleName='lambda-q-developer-role'),
            call(RoleName='lambda-iam-identity-center-extract-role')
        ]
        self.mock_iam.delete_role.assert_has_calls(expected_role_calls, any_order=True)

    def test_delete_iam_roles_not_found(self):
        """Test IAM roles deletion when roles don't exist"""
        self.mock_iam.delete_role_policy.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchEntity'}}, 'delete_role_policy'
        )
        self.mock_iam.delete_role.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchEntity'}}, 'delete_role'
        )
        
        # Should not raise exception
        self.cleanup.delete_iam_roles_and_policies()

    def test_delete_cloudtrail_success(self):
        """Test successful CloudTrail deletion"""
        self.cleanup.delete_cloudtrail()
        
        expected_trail_name = f"q-developer-3p-trail-{self.bucket_name}"
        self.mock_cloudtrail.delete_trail.assert_called_once_with(Name=expected_trail_name)

    def test_delete_cloudtrail_not_found(self):
        """Test CloudTrail deletion when trail doesn't exist"""
        self.mock_cloudtrail.delete_trail.side_effect = ClientError(
            {'Error': {'Code': 'TrailNotFoundException'}}, 'delete_trail'
        )
        
        # Should not raise exception
        self.cleanup.delete_cloudtrail()

    def test_empty_s3_bucket_success(self):
        """Test successful S3 bucket emptying"""
        # Mock bucket exists
        self.mock_s3.head_bucket.return_value = {}
        
        # Mock paginator for objects
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {'Contents': [{'Key': 'file1.txt'}, {'Key': 'file2.txt'}]}
        ]
        self.mock_s3.get_paginator.return_value = mock_paginator
        
        self.cleanup.empty_s3_bucket()
        
        # Verify head_bucket call
        self.mock_s3.head_bucket.assert_called_once_with(Bucket=self.bucket_name)
        
        # Verify delete_objects call
        expected_objects = [{'Key': 'file1.txt'}, {'Key': 'file2.txt'}]
        self.mock_s3.delete_objects.assert_called_with(
            Bucket=self.bucket_name,
            Delete={'Objects': expected_objects}
        )

    def test_empty_s3_bucket_not_found(self):
        """Test S3 bucket emptying when bucket doesn't exist"""
        self.mock_s3.head_bucket.side_effect = ClientError(
            {'Error': {'Code': '404'}}, 'head_bucket'
        )
        
        # Should not raise exception
        self.cleanup.empty_s3_bucket()

    def test_delete_s3_bucket_success(self):
        """Test successful S3 bucket deletion"""
        self.cleanup.delete_s3_bucket()
        
        self.mock_s3.delete_bucket.assert_called_once_with(Bucket=self.bucket_name)

    def test_delete_s3_bucket_not_found(self):
        """Test S3 bucket deletion when bucket doesn't exist"""
        self.mock_s3.delete_bucket.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchBucket'}}, 'delete_bucket'
        )
        
        # Should not raise exception
        self.cleanup.delete_s3_bucket()

    @patch('builtins.print')
    def test_run_cleanup_success(self, mock_print):
        """Test complete cleanup process"""
        # Mock all operations to succeed
        self.mock_events.list_targets_by_rule.return_value = {'Targets': []}
        self.mock_s3.head_bucket.return_value = {}
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{}]  # Empty bucket
        self.mock_s3.get_paginator.return_value = mock_paginator
        
        self.cleanup.run_cleanup()
        
        # Verify all cleanup methods were called
        self.mock_events.delete_rule.assert_called()
        self.mock_lambda.delete_function.assert_called()
        self.mock_iam.delete_role.assert_called()
        self.mock_cloudtrail.delete_trail.assert_called()
        self.mock_s3.delete_bucket.assert_called()


if __name__ == '__main__':
    unittest.main()
