#!/usr/bin/env python3
"""
GitLab MR CODEOWNERS Pipeline Check Script

This script validates that MR approvers are authorized according to CODEOWNERS.md files
in the directory hierarchy of changed files.
"""

import os
import sys
import json
import requests
from pathlib import Path
from typing import List, Set, Dict, Optional

class CodeownersChecker:
    def __init__(self):
        # GitLab CI environment variables
        self.gitlab_token = os.environ.get('GITLAB_TOKEN')
        self.ci_api_v4_url = os.environ.get('CI_API_V4_URL')
        self.ci_project_id = os.environ.get('CI_PROJECT_ID')
        self.ci_merge_request_iid = os.environ.get('CI_MERGE_REQUEST_IID')
        self.ci_project_dir = os.environ.get('CI_PROJECT_DIR', '.')
        
        if not all([self.gitlab_token, self.ci_api_v4_url, self.ci_project_id, self.ci_merge_request_iid]):
            raise ValueError("Missing required GitLab CI environment variables")
        
        self.headers = {'PRIVATE-TOKEN': self.gitlab_token}
        self.base_url = f"{self.ci_api_v4_url}/projects/{self.ci_project_id}"
    
    def get_mr_details(self) -> Dict:
        """Fetch merge request details from GitLab API"""
        url = f"{self.base_url}/merge_requests/{self.ci_merge_request_iid}"
        print(url)
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching MR details: {e}")
            sys.exit(1)
    
    def get_mr_approvals(self) -> List[str]:
        """Get list of users who approved the MR"""
        url = f"{self.base_url}/merge_requests/{self.ci_merge_request_iid}/approvals"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            approvals_data = response.json()
            
            # Extract usernames from approved_by list
            approvers = []
            for approval in approvals_data.get('approved_by', []):
                user = approval.get('user', {})
                username = user.get('username')
                if username:
                    approvers.append(username)
            
            return approvers
        except requests.RequestException as e:
            print(f"Error fetching MR approvals: {e}")
            sys.exit(1)
    
    def get_changed_files(self) -> List[str]:
        """Get list of files changed in the MR"""
        url = f"{self.base_url}/merge_requests/{self.ci_merge_request_iid}/changes"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            changes_data = response.json()
            
            changed_files = []
            for change in changes_data.get('changes', []):
                # Handle both new and old paths for renamed files
                if change.get('new_path'):
                    changed_files.append(change['new_path'])
                if change.get('old_path') and change['old_path'] != change.get('new_path'):
                    changed_files.append(change['old_path'])
            
            return changed_files
        except requests.RequestException as e:
            print(f"Error fetching MR changes: {e}")
            sys.exit(1)
    
    def read_codeowners_file(self, file_path: str) -> Set[str]:
        """Read CODEOWNERS.md file and extract usernames"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            owners = set()
            for line in content.splitlines():
                print("line:",line)
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                
                # Extract usernames (assuming format: @username or username)
                words = line.split()
                for word in words:
                    if word.startswith('@'):
                        owners.add(word[1:])  # Remove @ prefix
                    elif word and not word.startswith('/') and not word.startswith('*'):
                        # Assume it's a username if it doesn't look like a path pattern
                        owners.add(word)
            
            return owners
        except FileNotFoundError:
            return set()
        except Exception as e:
            print(f"Error reading CODEOWNERS file {file_path}: {e}")
            return set()
    
    def get_codeowners_for_file(self, file_path: str) -> Set[str]:
        """Get all codeowners for a file by checking directory hierarchy"""
        all_owners = set()
        current_path = Path(file_path).parent
        print("current_path:",current_path)
        
        # Check current directory and all parent directories
        while True:
            codeowners_path = os.path.join(self.ci_project_dir, current_path, 'CODEOWNERS.md')
            print("codeowners_path:",codeowners_path)
            owners = self.read_codeowners_file(codeowners_path)
            all_owners.update(owners)
            
            # Stop if we've reached the root
            if current_path == Path('.') or current_path == Path('/'):
                break
            
            current_path = current_path.parent
        
        # Also check root CODEOWNERS.md
        root_codeowners = os.path.join(self.ci_project_dir, 'CODEOWNERS.md')
        all_owners.update(self.read_codeowners_file(root_codeowners))
        
        return all_owners
    
    def validate_approvals(self) -> bool:
        """Main validation logic"""
        print("🔍 Starting CODEOWNERS validation...")
        
        # Get MR details
        mr_details = self.get_mr_details()
        print(f"📋 Checking MR !{mr_details.get('iid')}: {mr_details.get('title')}")
        
        # Get approvers
        approvers = self.get_mr_approvals()
        if not approvers:
            print("❌ No approvals found for this MR")
            return False
        
        print(f"👥 Approvers: {', '.join(approvers)}")
        
        # Get changed files
        changed_files = self.get_changed_files()
        if not changed_files:
            print("✅ No files changed, validation passed")
            return True
        
        print(f"📁 Changed files ({len(changed_files)}):")
        for file in changed_files:
            print(f"   - {file}")
        
        # Validate each changed file
        validation_failed = False
        
        for file_path in changed_files:
            print(f"\n🔎 Checking: {file_path}")
            
            # Get all codeowners for this file
            file_owners = self.get_codeowners_for_file(file_path)
            
            if not file_owners:
                print(f"   ⚠️  No CODEOWNERS found in directory hierarchy")
                continue
            
            print(f"   👤 Required owners: {', '.join(sorted(file_owners))}")
            
            # Check if any approver is a codeowner
            authorized_approvers = set(approvers) & file_owners
            
            if authorized_approvers:
                print(f"   ✅ Authorized approver(s): {', '.join(authorized_approvers)}")
            else:
                print(f"   ❌ No authorized approvers found!")
                print(f"      Required: {', '.join(sorted(file_owners))}")
                print(f"      Actual: {', '.join(approvers)}")
                validation_failed = True
        
        if validation_failed:
            print(f"\n❌ CODEOWNERS validation FAILED")
            print("Some files don't have proper approvals from their codeowners.")
            return False
        else:
            print(f"\n✅ CODEOWNERS validation PASSED")
            print("All changed files have been approved by authorized codeowners.")
            return True

def main():
    """Main entry point"""
    try:

        checker = CodeownersChecker()
        success = checker.validate_approvals()
        sys.exit(0 if success else 1)
    
    except Exception as e:
        print(f"❌ Script failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
