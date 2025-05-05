from serpapi import GoogleSearch
from newspaper import Article
from config import SERPAPI_API_KEY


def search_news_links(company_name, num_results=5):
    search = GoogleSearch({
        "q": company_name,
        "tbm": "nws",
        "api_key": SERPAPI_API_KEY,
        "num": num_results
    })
    results = search.get_dict()
    return [r["link"] for r in results.get("news_results", []) if "link" in r]


def scrape_article(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text.strip()
    except Exception:
        return None


def get_scraped_news(company_name):
    links = search_news_links(company_name)
    articles = []
    for link in links:
        text = scrape_article(link)
        if text:
            articles.append({"url": link, "content": text})
    return articles
