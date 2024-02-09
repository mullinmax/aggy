# blinder



## TODO
- [ ] make side menu useable
    - [ ] add an edit/delete button/route for feeds
    - [ ] when adding feed suggest categories/autofill
- [ ] pagination
- [ ] add published date, favicon and metadata to items
- [ ] add feed management + stats(opens, % open, new since last open)
- [ ] collect user data (opens, up and down votes)
- [ ] break image collection into seperate microservice
- [ ] create embeddings microservice for text/images
- [ ] create microservice for training models on embeddings and user data
- [ ] find most relevant image on a website using embeddings?
- [ ] fix reddit albums getting very low res thumbnails
- [ ] de-duplicate posts where possible (same title, picture(maybe based on embeddings?), link after redirects)



### Database Design

```mermaid
flowchart TD

    subgraph key
        set{{set}}
        ordered_set([ordered set])
        string[string]
        hash>hash]
        list[[list]]
    end

    categories(["
        CATEGORIES
        order implies menu order
    "])
    
    schema_version["SCHEMA_VERSION"]
    category_feeds(["
        CATEGORY:tech-news:FEEDS
        order implies menu order
    "])

    feed>"
        FEED:Tesla 🚗⚡
    "]

    url[tesla-news.com/rss]
    model[model]
    feed_items{{"
        FEED:Tesla 🚗⚡:ITEMS
        sort by: score
    "}}
    unread_feed_items{{"
        FEED:Tesla 🚗⚡:UNREAD_ITEMS
        sort by: score
    "}}

    

    item>FEED:Tesla 🚗⚡:ITEM:https://tesla.com/blog/1]

    item --> link
    item --> title
    item --> content
    item --> user_vote["user vote"]
    
    item --> image

    categories --tech-news--> category_feeds
    category_feeds --Tesla 🚗⚡--> feed
    feed --url--> url
    feed --model--> model
    feed --unread_items_key--> unread_feed_items
    feed --items_key--> feed_items
    unread_feed_items --> item
    feed_items --> item

```
