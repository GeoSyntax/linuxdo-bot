import scrapy


class AnswerItem(scrapy.Item):
    answer_id = scrapy.Field()
    question_title = scrapy.Field()
    author = scrapy.Field()
    content_html = scrapy.Field()
    content_markdown = scrapy.Field()
    voteup_count = scrapy.Field()
    comment_count = scrapy.Field()
    url = scrapy.Field()
    sentiment = scrapy.Field()
    is_cleaned = scrapy.Field()
    crawled_at = scrapy.Field()
