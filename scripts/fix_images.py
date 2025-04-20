import os
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json
import argparse
import glob
import time
import random

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("Loaded environment variables from .env file")
except ImportError:
    print("dotenv module not installed, will use environment variables directly")

def get_producthunt_token():
    """Get Product Hunt access token"""
    # First try to use PRODUCTHUNT_DEVELOPER_TOKEN environment variable
    developer_token = os.getenv('PRODUCTHUNT_DEVELOPER_TOKEN')
    if developer_token:
        print("Using PRODUCTHUNT_DEVELOPER_TOKEN environment variable")
        return developer_token
    
    # If no developer token, try to get access token using client credentials
    client_id = os.getenv('PRODUCTHUNT_CLIENT_ID')
    client_secret = os.getenv('PRODUCTHUNT_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        raise Exception("Product Hunt client ID or client secret not found in environment variables")
    
    # Get access token using client credentials
    token_url = "https://api.producthunt.com/v2/oauth/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    }
    
    try:
        response = requests.post(token_url, json=payload)
        response.raise_for_status()
        token_data = response.json()
        return token_data.get("access_token")
    except Exception as e:
        print(f"Error getting Product Hunt access token: {e}")
        raise Exception(f"Failed to get Product Hunt access token: {e}")

def fetch_product_image(product_url, token, retry_count=0, max_retries=3):
    """Get product image URL from Product Hunt API"""
    # Extract product slug from URL
    match = re.search(r'/posts/([^?]+)', product_url)
    if not match:
        print(f"Could not extract product slug from URL: {product_url}")
        return None
    
    slug = match.group(1)
    
    # Build GraphQL query
    query = """
    {
      post(slug: "%s") {
        name
        media {
          url
          type
        }
      }
    }
    """ % slug
    
    url = "https://api.producthunt.com/v2/api/graphql"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "ImageFixScript/1.0"
    }
    
    try:
        # Add random delay to avoid frequent requests
        delay = 2 + random.random() * 3  # Random delay of 2-5 seconds
        print(f"Waiting {delay:.2f} seconds before API request...")
        time.sleep(delay)
        
        response = requests.post(url, headers=headers, json={"query": query})
        
        # Handle 429 error (too many requests)
        if response.status_code == 429:
            if retry_count < max_retries:
                retry_delay = (2 ** retry_count) * 10  # Exponential backoff: 10, 20, 40seconds...
                print(f"Too many API requests (429), retrying in {retry_delay} seconds ({retry_count + 1}/{max_retries})...")
                time.sleep(retry_delay)
                return fetch_product_image(product_url, token, retry_count + 1, max_retries)
            else:
                print(f"Maximum retries reached, unable to get image from API: {product_url}")
                return None
        
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and 'post' in data['data'] and data['data']['post'] and 'media' in data['data']['post']:
            media = data['data']['post']['media']
            if media and len(media) > 0:
                return media[0]['url']
        
        print(f"No image URL found in API response data: {json.dumps(data)}")
        return None
    except Exception as e:
        print(f"Error getting product image URL: {e}")
        
        # Retry on network or server errors
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)) or \
           (isinstance(e, requests.exceptions.HTTPError) and e.response.status_code >= 500):
            if retry_count < max_retries:
                retry_delay = (2 ** retry_count) * 5  # Exponential backoff: 5, 10, 20seconds...
                print(f"Network error, retrying in {retry_delay} seconds ({retry_count + 1}/{max_retries})...")
                time.sleep(retry_delay)
                return fetch_product_image(product_url, token, retry_count + 1, max_retries)
        
        return None

def fetch_og_image_url(url, retry_count=0, max_retries=3):
    """Get Open Graph image URL from webpage (backup method)"""
    try:
        # Add random delay to avoid frequent requests
        delay = 1 + random.random() * 2  # Random delay of 1-3 seconds
        print(f"Waiting {delay:.2f} seconds before web request...")
        time.sleep(delay)
        
        response = requests.get(url, timeout=15)
        
        # Handle 429 error (too many requests)
        if response.status_code == 429:
            if retry_count < max_retries:
                retry_delay = (2 ** retry_count) * 5  # Exponential backoff: 5, 10, 20seconds...
                print(f"Too many web requests (429), retrying in {retry_delay} seconds ({retry_count + 1}/{max_retries})...")
                time.sleep(retry_delay)
                return fetch_og_image_url(url, retry_count + 1, max_retries)
            else:
                print(f"Maximum retries reached, unable to get image from webpage: {url}")
                return None
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Look for og:image meta tag
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                return og_image["content"]
            # Backup: look for twitter:image meta tag
            twitter_image = soup.find("meta", name="twitter:image") 
            if twitter_image and twitter_image.get("content"):
                return twitter_image["content"]
        return None
    except Exception as e:
        print(f"Error getting OG image URL: {url}, Error: {e}")
        
        # Retry on network or server errors
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)) and retry_count < max_retries:
            retry_delay = (2 ** retry_count) * 5  # Exponential backoff: 5, 10, 20seconds...
            print(f"Network error, retrying in {retry_delay} seconds ({retry_count + 1}/{max_retries})...")
            time.sleep(retry_delay)
            return fetch_og_image_url(url, retry_count + 1, max_retries)
        
        return None

def fix_markdown_file(file_path, token):
    """Fix missing image links in Markdown file"""
    print(f"Processing file: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Use regex to find product blocks
    product_blocks = re.findall(r'## \[\d+\. (.+?)\]\((.+?)\)[\s\S]+?!\[\1\]\(([^\)]*)\)', content)
    
    if not product_blocks:
        print(f"No product blocks found in file: {file_path}")
        return False
    
    modified = False
    
    for product_name, product_url, image_url in product_blocks:
        # If image URL is empty, try to get it
        if not image_url:
            print(f"Getting product image URL: {product_name}")
            
            # First try to get from API
            new_image_url = fetch_product_image(product_url, token)
            
            # If API fails, try to get from webpage
            if not new_image_url:
                print(f"Failed to get image URL from API, trying webpage: {product_name}")
                new_image_url = fetch_og_image_url(product_url)
            
            if new_image_url:
                print(f"Successfully got image URL: {product_name} -> {new_image_url}")
                # Replace image URL
                old_pattern = f"![{product_name}]()"
                new_pattern = f"![{product_name}]({new_image_url})"
                content = content.replace(old_pattern, new_pattern)
                modified = True
            else:
                print(f"Unable to get image URL for: {product_name}")
    
    if modified:
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)
        print(f"Updated file: {file_path}")
        return True
    else:
        print(f"No changes needed for file: {file_path}")
        return False

def process_files_in_batches(files, token, batch_size=5, pause_between_batches=60):
    """Process files in batches with pauses between batches"""
    total_files = len(files)
    print(f"Total files to process {total_files} files, batch size {batch_size} with pause of {pause_between_batches} seconds")
    
    for i in range(0, total_files, batch_size):
        batch = files[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total_files + batch_size - 1) // batch_size
        
        print(f"\nProcessing batch {batch_num}/{total_batches} of files...")
        
        for file_path in batch:
            fix_markdown_file(file_path, token)
        
        # 如果不是最后一批，暂停一段时间
        if i + batch_size < total_files:
            print(f"\n第 {batch_num}/{total_batches} batch completed, pausing for {pause_between_batches} seconds后继续...")
            time.sleep(pause_between_batches)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Fix missing image links in Markdown file')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)', default='2025-02-22')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)', default='2025-03-10')
    parser.add_argument('--file', help='Specify a single file to fix')
    parser.add_argument('--all', action='store_true', help='Fix all files in data directory')
    parser.add_argument('--batch-size', type=int, default=5, help='Number of files to process per batch')
    parser.add_argument('--pause', type=int, default=60, help='批次间暂停的seconds数')
    args = parser.parse_args()
    
    # Get Product Hunt access token
    token = get_producthunt_token()
    
    if args.file:
        # Fix specified single file
        if os.path.exists(args.file):
            fix_markdown_file(args.file, token)
        else:
            print(f"File does not exist: {args.file}")
    elif args.all:
        # Fix all files in data directory
        files = glob.glob('data/producthunt-daily-*.md')
        process_files_in_batches(sorted(files), token, args.batch_size, args.pause)
    else:
        # Fix files within specified date range
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
        except ValueError:
            print("日期格式Error，请使用 YYYY-MM-DD 格式")
            return
        
        # Collect all files within specified date range
        files = []
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            file_path = f"data/producthunt-daily-{date_str}.md"
            
            if os.path.exists(file_path):
                files.append(file_path)
            else:
                print(f"File does not exist: {file_path}")
            
            current_date += timedelta(days=1)
        
        # Process files in batches
        if files:
            process_files_in_batches(files, token, args.batch_size, args.pause)
        else:
            print("No files found to process")

if __name__ == "__main__":
    main() 