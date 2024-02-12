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
flowchart TB

    subgraph Legend
        direction LR
        set{{set}}
        ordered_set([sortered set])
        string[string]
        hash>hash]
        list[[list]]
        key[\key/]
    end

    subgraph User Space
        user>USER:username_hash] 
        user--password--> password_hash[password hash]
        user--username--> username[username]
        user--key-->misc_user_settings[misc user settings]
        
        categories([USER:username:CATEGORIES])
        category>USER:username:CATEGORY:category]
        category_model[category model]
        category_feeds([USER:user:CATEGORY:category:FEEDS])
        feed>USER:username:FEED:feedname]
        feed_url[feed url]
        items([USER:username:FEED:feedname:ITEMS])
        items_subset{{USER:username:FEED:feedname:ITEMS_SUBSET liked/read}}

        categories --> category
        category --model--> category_model
        category -.-> category_feeds
        category_feeds --> feed
        feed --url--> feed_url
        feed --items_key--> items
        feed --> items_subset
    end

    items-->item
    items_subset-->item
    item>ITEM:url]
    item-->title
    item-->content
    item-->score
    item-->refrence_count
    schema_version[SCHEMA_VERSION]

```


### old design
---
```mermaid
flowchart TD

    subgraph legend
        set{{set}}
        ordered_set([sortered set])
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
        CATEGORY:tech-news:FEED:Tesla 🚗⚡
    "]

    url[tesla-news.com/rss]
    model[model]
    feed_items{{"
        CATEGORY:tech-news:FEED:Tesla 🚗⚡:ITEMS
        sort by: score
    "}}
    unread_feed_items{{"
        CATEGORY:tech-news:FEED:Tesla 🚗⚡:UNREAD_ITEMS
        sort by: score
    "}}

    

    item>CATEGORY:tech-news:FEED:Tesla 🚗⚡:ITEM:https://tesla.com/blog/1]

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
