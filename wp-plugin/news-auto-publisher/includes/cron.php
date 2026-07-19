<?php

function news_auto_pub_setup_cron() {
    add_action('news_auto_pub_hourly_event', 'news_auto_pub_cron_job');
}

function news_auto_pub_cron_job() {
    // This is the function that runs on the cron schedule
    news_auto_pub_fetch_and_publish();
}

// Add a manual trigger for testing
add_action('admin_post_news_auto_pub_manual_trigger', 'news_auto_pub_manual_trigger');
function news_auto_pub_manual_trigger() {
    if (!current_user_can('manage_options')) {
        wp_die('Unauthorized');
    }
    
    news_auto_pub_fetch_and_publish();
    
    wp_redirect(admin_url('options-general.php?page=news-auto-publisher&status=success'));
    exit;
}

// Add manual trigger button to settings page
add_action('admin_notices', 'news_auto_pub_add_manual_button');
function news_auto_pub_add_manual_button() {
    $screen = get_current_screen();
    if ($screen->id === 'settings_page_news-auto-publisher') {
        if (isset($_GET['status']) && $_GET['status'] == 'success') {
            echo '<div class="notice notice-success is-dismissible"><p>News fetched and published successfully!</p></div>';
        }
        
        $url = admin_url('admin-post.php?action=news_auto_pub_manual_trigger');
        echo '<div class="notice notice-info"><p><a href="' . esc_url($url) . '" class="button button-primary">Fetch News Now (Manual Trigger)</a></p></div>';
    }
}
