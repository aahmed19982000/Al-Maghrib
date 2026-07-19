<?php
// Settings Page for the Plugin

function news_auto_pub_add_admin_menu() {
    add_options_page(
        'News Auto Publisher', 
        'News Publisher', 
        'manage_options', 
        'news-auto-publisher', 
        'news_auto_pub_options_page'
    );
}
add_action('admin_menu', 'news_auto_pub_add_admin_menu');

function news_auto_pub_settings_init() {
    register_setting('news_auto_pub_settings', 'news_auto_pub_api_url');
    register_setting('news_auto_pub_settings', 'news_auto_pub_daily_limit');
    register_setting('news_auto_pub_settings', 'news_auto_pub_facebook_connect_url');
}
add_action('admin_init', 'news_auto_pub_settings_init');

function news_auto_pub_options_page() {
    $fb_connect_url = get_option('news_auto_pub_facebook_connect_url', '');
    ?>
    <div class="wrap">
        <h2>News Auto Publisher Settings</h2>
        <form action="options.php" method="post">
            <?php
            settings_fields('news_auto_pub_settings');
            do_settings_sections('news_auto_pub_settings');
            ?>
            <table class="form-table">
                <tr valign="top">
                    <th scope="row">API URL (Al-Maghrib Django API)</th>
                    <td>
                        <input type="text" name="news_auto_pub_api_url" value="<?php echo esc_attr(get_option('news_auto_pub_api_url', 'http://127.0.0.1:8000/api/articles/')); ?>" class="regular-text" style="width: 400px;" />
                        <p class="description">يجب أن ينتهي الرابط بـ /api/articles/</p>
                    </td>
                </tr>
                <tr valign="top">
                    <th scope="row">Articles per fetch (Limit)</th>
                    <td><input type="number" name="news_auto_pub_daily_limit" value="<?php echo esc_attr(get_option('news_auto_pub_daily_limit', '5')); ?>" /></td>
                </tr>
                <tr valign="top">
                    <th scope="row">ربط صفحة فيسبوك (Facebook Page)</th>
                    <td>
                        <input type="text" name="news_auto_pub_facebook_connect_url" id="news_auto_pub_facebook_connect_url" value="<?php echo esc_attr($fb_connect_url); ?>" class="regular-text" style="width: 400px;" placeholder="سيزودك فريق الدعم بهذا الرابط" />
                        <p class="description">الصق هنا رابط الربط الذي يزودك به فريق الدعم لهذا الموقع، ثم احفظ الإعدادات، وبعدها اضغط الزر أدناه لربط صفحة فيسبوك الخاصة بك.</p>
                        <?php if ($fb_connect_url) : ?>
                            <p>
                                <a href="<?php echo esc_url($fb_connect_url); ?>" target="_blank" class="button button-primary" style="margin-top:8px;">
                                    ربط صفحة فيسبوك الآن
                                </a>
                            </p>
                        <?php endif; ?>
                    </td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}
