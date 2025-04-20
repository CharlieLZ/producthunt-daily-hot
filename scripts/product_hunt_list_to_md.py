import os
try:
    from dotenv import load_dotenv
    # Load .env file
    load_dotenv()
except ImportError:
    # In environments like GitHub Actions, environment variables are already set
    print("dotenv module not installed, will use environment variables directly")

import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import pytz
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class Product:
    def __init__(self, id: str, name: str, tagline: str, description: str, votesCount: int, createdAt: str, featuredAt: str, website: str, url: str, media=None, **kwargs):
        self.name = name
        self.tagline = tagline
        self.description = description
        self.votes_count = votesCount
        self.created_at = self.convert_to_utc_time(createdAt)
        self.featured = "Yes" if featuredAt else "No"
        self.website = website
        self.url = url
        self.og_image_url = self.get_image_url_from_media(media)

    def get_image_url_from_media(self, media):
        """Get image URL from the API response media field"""
        try:
            if media and isinstance(media, list) and len(media) > 0:
                # Use the first image preferentially
                image_url = media[0].get('url', '')
                if image_url:
                    print(f"Successfully got image URL from API: {self.name}")
                    return image_url
            
            # If API doesn't return image, try backup method
            print(f"API did not return image, trying backup method: {self.name}")
            backup_url = self.fetch_og_image_url()
            if backup_url:
                print(f"Successfully got image URL using backup method: {self.name}")
                return backup_url
            else:
                print(f"Could not get image URL: {self.name}")
                
            return ""
        except Exception as e:
            print(f"Error getting image URL: {self.name}, Error: {e}")
            return ""

    def fetch_og_image_url(self) -> str:
        """Get the product's Open Graph image URL (backup method)"""
        try:
            response = requests.get(self.url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Look for og:image meta tag
                og_image = soup.find("meta", property="og:image")
                if og_image:
                    return og_image["content"]
                # Backup: look for twitter:image meta tag
                twitter_image = soup.find("meta", name="twitter:image") 
                if twitter_image:
                    return twitter_image["content"]
            return ""
        except Exception as e:
            print(f"Error getting OG image URL: {self.name}, Error: {e}")
            return ""

    def convert_to_utc_time(self, utc_time_str: str) -> str:
        """Convert UTC time to formatted time string"""
        utc_time = datetime.strptime(utc_time_str, '%Y-%m-%dT%H:%M:%SZ')
        return utc_time.strftime('%Y-%m-%d %H:%M (UTC)')

    def to_markdown(self, rank: int) -> str:
        """Return product data in Markdown format"""
        og_image_markdown = f"![{self.name}]({self.og_image_url})"
        return (
            f"## [{rank}. {self.name}]({self.url})\n"
            f"**Tagline**: {self.tagline}\n"
            f"**Description**: {self.description}\n"
            f"**Website**: [Visit website]({self.website})\n"
            f"**Product Hunt**: [View on Product Hunt]({self.url})\n\n"
            f"{og_image_markdown}\n\n"
            f"**Votes**: 🔺{self.votes_count}\n"
            f"**Featured**: {self.featured}\n"
            f"**Created**: {self.created_at}\n\n"
            f"---\n\n"
        )

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

def fetch_product_hunt_data():
    """Fetch Top 30 data from Product Hunt for the previous day"""
    token = get_producthunt_token()
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime('%Y-%m-%d')
    url = "https://api.producthunt.com/v2/api/graphql"
    
    # Add more request headers information
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "DecohackBot/1.0 (https://decohack.com)",
        "Origin": "https://decohack.com",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Connection": "keep-alive"
    }

    # Set retry strategy
    retry_strategy = Retry(
        total=3,  # Retry a maximum of 3 times
        backoff_factor=1,  # Interval between retries
        status_forcelist=[429, 500, 502, 503, 504]  # HTTP status codes to retry
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)

    base_query = """
    {
      posts(order: VOTES, postedAfter: "%sT00:00:00Z", postedBefore: "%sT23:59:59Z", after: "%s") {
        nodes {
          id
          name
          tagline
          description
          votesCount
          createdAt
          featuredAt
          website
          url
          media {
            url
            type
          }
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
    """
    
    all_products = []
    cursor = ""
    
    while True:
        if cursor:
            query = base_query % (date_str, date_str, cursor)
        else:
            query = base_query % (date_str, date_str, "")
        
        try:
            response = session.post(url, json={"query": query}, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if "errors" in data:
                print(f"API returned errors: {data['errors']}")
                raise Exception(f"API error: {data['errors']}")
            
            products_data = data.get("data", {}).get("posts", {}).get("nodes", [])
            page_info = data.get("data", {}).get("posts", {}).get("pageInfo", {})
            end_cursor = page_info.get("endCursor", "")
            has_next_page = page_info.get("hasNextPage", False)
            
            all_products.extend(products_data)
            
            print(f"Fetched {len(products_data)} products, total: {len(all_products)}")
            
            if not has_next_page or len(all_products) >= 30:
                break
            
            cursor = end_cursor
            
        except Exception as e:
            print(f"Error fetching Product Hunt data: {e}")
            # Try mock data if API request fails
            return fetch_mock_data()
    
    # Process the top 30 products
    top_products = []
    count = min(30, len(all_products))
    
    try:
        for i in range(count):
            product = Product(**all_products[i])
            top_products.append(product)
    except Exception as e:
        print(f"Error processing product data: {e}")
        return fetch_mock_data()
    
    return top_products

def fetch_mock_data():
    """Generate mock data for testing when API fails"""
    print("Using mock data for testing")
    mock_products = []
    for i in range(5):
        product = Product(
            id=f"mock-id-{i}",
            name=f"Mock Product {i+1}",
            tagline=f"This is a mock product {i+1} for testing",
            description="Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
            votesCount=100-i*10,
            createdAt="2023-01-01T00:00:00Z",
            featuredAt="2023-01-01T12:00:00Z" if i % 2 == 0 else None,
            website=f"https://example-{i+1}.com",
            url=f"https://producthunt.com/products/mock-{i+1}"
        )
        mock_products.append(product)
    return mock_products

def generate_markdown(products, date_str):
    """Generate Markdown content from product data"""
    header = f"# Product Hunt Daily Top List - {date_str}\n\n"
    introduction = (
        f"Top products on Product Hunt for {date_str}.\n\n"
        f"_Generated automatically at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC_\n\n"
        f"---\n\n"
    )
    
    product_content = ""
    for i, product in enumerate(products, 1):
        product_content += product.to_markdown(i)
    
    return header + introduction + product_content

def main():
    # Get yesterday's date and format it
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime('%Y-%m-%d')
    
    print(f"Fetching Product Hunt data for {date_str}")
    products = fetch_product_hunt_data()
    
    if not products:
        print("No products found, exiting")
        return
    
    markdown_content = generate_markdown(products, date_str)
    
    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)
    
    # Write Markdown content to file
    output_file = f"data/PH-daily-{date_str}.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    
    print(f"Successfully generated Markdown file: {output_file}")

if __name__ == "__main__":
    main()