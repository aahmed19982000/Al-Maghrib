<?php

require_once(ABSPATH . 'wp-admin/includes/media.php');
require_once(ABSPATH . 'wp-admin/includes/file.php');
require_once(ABSPATH . 'wp-admin/includes/image.php');

function news_auto_pub_fetch_and_publish() {
    $api_url = get_option('news_auto_pub_api_url', 'http://127.0.0.1:8000/api/articles/');
    $limit = get_option('news_auto_pub_daily_limit', 5);

    // Django DRF pagination might be present, but we can try fetching the first page
    $request_url = $api_url;
    
    $response = wp_remote_get($request_url, array('timeout' => 30));
    
    if (is_wp_error($response)) {
        error_log("News Auto Publisher: API request failed. " . $response->get_error_message());
        return;
    }

    $body = wp_remote_retrieve_body($response);
    $data = json_decode($body, true);
    
    // Handle Django REST Framework pagination (usually returns {count, next, previous, results})
    $articles = isset($data['results']) ? $data['results'] : $data;
    
    if (empty($articles) || !is_array($articles)) {
        return;
    }
    
    $count = 0;
    foreach ($articles as $article) {
        if ($count >= $limit) break;

        // Check if already published by Title
        $existing_post = get_page_by_title($article['title'], OBJECT, 'post');
        if ($existing_post) {
            continue;
        }

        $category_name = isset($article['category']['name']) ? $article['category']['name'] : 'عام';
        $tags = isset($article['tags']) && is_array($article['tags']) ? implode(',', $article['tags']) : '';

        // Prepare post data
        $post_data = array(
            'post_title'    => wp_strip_all_tags($article['title']),
            'post_content'  => wp_kses_post($article['body']),
            'post_excerpt'  => wp_strip_all_tags($article['excerpt']),
            'post_status'   => 'publish',
            'post_author'   => 1,
            'post_category' => array(news_auto_pub_get_or_create_category($category_name)),
            'tags_input'    => $tags
        );

        // Insert the post into the database
        $post_id = wp_insert_post($post_data);
        
        if ($post_id && !is_wp_error($post_id)) {
            // Upload and attach image
            if (!empty($article['cover_image'])) {
                // DRF might return relative URL, ensure it's absolute
                $image_url = $article['cover_image'];
                if (strpos($image_url, 'http') !== 0) {
                    $parsed_url = parse_url($api_url);
                    $base_url = $parsed_url['scheme'] . '://' . $parsed_url['host'] . (isset($parsed_url['port']) ? ':' . $parsed_url['port'] : '');
                    $image_url = $base_url . $image_url;
                }
                
                $attach_id = news_auto_pub_upload_image($image_url, $post_id, $article['title']);
                if ($attach_id) {
                    set_post_thumbnail($post_id, $attach_id);
                }
            }
            $count++;
        }
    }
}

function news_auto_pub_get_or_create_category($cat_name) {
    if (empty($cat_name)) {
        return 1; // Default category
    }
    
    $term = term_exists($cat_name, 'category');
    if ($term !== 0 && $term !== null) {
        return $term['term_id'];
    }
    
    $new_term = wp_insert_term($cat_name, 'category');
    if (!is_wp_error($new_term)) {
        return $new_term['term_id'];
    }
    return 1;
}

function news_auto_pub_upload_image($image_url, $post_id, $desc) {
    $tmp = download_url($image_url);
    if (is_wp_error($tmp)) {
        return false;
    }

    $file_array = array(
        'name' => basename(parse_url($image_url, PHP_URL_PATH)),
        'tmp_name' => $tmp
    );

    if (!preg_match('!\.\w+$!', $file_array['name'])) {
        $file_array['name'] .= '.jpg';
    }

    $attach_id = media_handle_sideload($file_array, $post_id, $desc);
    if (is_wp_error($attach_id)) {
        @unlink($file_array['tmp_name']);
        return false;
    }
    return $attach_id;
}
