<?php
/**
 * Plugin Name: News Auto Publisher (Gemini API)
 * Description: Automatically fetches rewritten news from our central Python API and publishes them to WordPress.
 * Version: 1.0.0
 * Author: Antigravity
 */

if (!defined('ABSPATH')) {
    exit;
}

// Include files
require_once plugin_dir_path(__FILE__) . 'includes/settings.php';
require_once plugin_dir_path(__FILE__) . 'includes/api-fetcher.php';
require_once plugin_dir_path(__FILE__) . 'includes/cron.php';

// Initialize the plugin
function news_auto_pub_init() {
    news_auto_pub_setup_cron();
}
add_action('init', 'news_auto_pub_init');

// Activation Hook
register_activation_hook(__FILE__, 'news_auto_pub_activate');
function news_auto_pub_activate() {
    if (!wp_next_scheduled('news_auto_pub_hourly_event')) {
        wp_schedule_event(time(), 'hourly', 'news_auto_pub_hourly_event');
    }
}

// Deactivation Hook
register_deactivation_hook(__FILE__, 'news_auto_pub_deactivate');
function news_auto_pub_deactivate() {
    wp_clear_scheduled_hook('news_auto_pub_hourly_event');
}
