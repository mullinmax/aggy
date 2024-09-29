# Aggy 🐊

A self-hostable personalized content aggregator. It's like your own private reddit instance where the only vote that matters is yours.

## Why use Aggy?

Say you're into electric vehicles, but not general cars. You browse /r/mechanics but there's lots of popular posts in the subreddit that don't interest you. So you hop over to youtube and find a few videos you like but your favorite channels are posting lots of different content that isn't always your taste. Aggy is designed to solve this problem; it brings all your content into one place sorted by relevance to you. That means when you want EV-related content; you aren't sorting through the junk to find what you want.

## How does Aggy work?

#### How does Aggy get all my content in one place?

Aggy curently supports:
- RSS feeds with templates built on top of [RSS-Bridge](https://github.com/RSS-Bridge/rss-bridge)

Aggy will soon support:
- Email (sign up for news letters with an Aggy email and skip the spam)
- Podcasts (currently not searchable and only via RSS feeds)


When Aggy gets a new item in a feed it builds out some basic metadata and decides how likely it is that you will want to see it.

#### How does Aggy know what I like?

Aggy leverages [embeddings](https://stackoverflow.blog/2023/11/09/an-intuitive-introduction-to-text-embeddings/) to understand your content semantically. As you browse your content it learns what you like based on your clicks, likes, filters, and feedback.


## Features

### Available

- RSS feed support + predefined RSS feed templates
- Embedding generation for text

### Planned

- Automatically re-map URLs (i.e. youtube to [invidious](https://invidious.io/))
- Embedding Generation for images
- Train models on user feedback
- Duplicate post recognition (detect when very similar content is posted in seperate places and take just the best)
- Alternate sort orders (Best, Worst, Newest, Oldest)
- Reccomendation report (Why am I seeing this?)
- Semantic filters (Don't show me political content)
- Blur or block NSFW images/content

## Contributing

We don't have a contributing guide yet, maybe you could help us with that?

## License

[./LICENSE](LICENSE (Apache 2.0))






# TODO
- [ ] generate embeddings for images
- [ ] train models on user data + embeddings
- [ ] use embeddings to help decide which image would be the best preview image
- [ ] fix reddit albums getting very low res thumbnails
- [ ] de-duplicate posts where possible (same title, picture(maybe based on embeddings?), link after redirects)
- [ ] Add RSS bridge (or similar) to docker compose setup (use this to template rss feeds?)
- [ ] API for templated rss feeds


### Database Design

```mermaid
flowchart TB
    subgraph Legend
        direction LR
        set{{set}}
        sorted_set([sortered set])
        string[string]
        hash>hash]
        list[[list]]
        hash --linked by key-->string
        hash -.linked implicitly.-> sorted_set
    end

    feeds_to_ingest([FEED-KEYS-TO-INGEST]) --feed key--> feed

    subgraph User Space ALL keys prefixed with USER:username_hash:
        user>USER:username_hash]
        user--password--> password_hash[password hash]
        user--username--> username[username]
        user--key-->misc_user_settings[misc user settings]

        categories([CATEGORIES])
        category>CATEGORY:uuid]
        category_embeddings_model[category embeddings model]
        category_name[category name]
        category_feeds{{CATEGORY:uuid:FEEDS}}
        category_items([CATEGORY:uuid:ITEMS])
        feed>CATEGORY:uuid:FEED:name_hash]
        feed_url[url]
        feed_name[name]
        items([FEED:name_hash:ITEMS])


        categories --> category

        category --embeddings model--> category_embeddings_model
        category --name--> category_name
        category -.-> category_items
        category -.-> category_feeds
        category_feeds --> feed
        feed --url--> feed_url
        feed --name--> feed_name
        feed -.-> items

        items -.-> item_state[CATEGORY:hash:ITEM:hash:ITEM_STATE]

    end

    item[ITEM:url_hash]
    item_embeddings>ITEM:url_hash:EMBEDDINGS]
    item_embedding[item embedding]

    items-.->item
    item -.-> item_state
    category_items -.-> item
    category_items -.-> item_embeddings
    item_embeddings --model_name--> item_embedding
    item -.-> item_embeddings
    category_embeddings_model -.-> item_embedding
    users{{USERS}} --> user
    feed_templates{{FEED_TEMPLATES}} --> feed_template[FEED_TEMPLATE:hash]
```
