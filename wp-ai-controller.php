<?php
/**
 * Plugin Name: متحكم الأخبار بالذكاء الاصطناعي (AI News Controller)
 * Description: إضافة لربط موقع ووردبريس بنظام الجدولة والتوليد الآلي والتحكم في إعدادات النشر من لوحة التحكم.
 * Version: 1.0.0
 * Author: Antigravity AI
 * License: GPL2
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class WP_AI_News_Controller {

    public function __construct() {
        add_action( 'admin_menu', array( $this, 'add_admin_menu' ) );
        add_action( 'admin_init', array( $this, 'register_settings' ) );
        
        // Intercept REST API post creation to assign the selected author and categories
        add_action( 'rest_insert_post', array( $this, 'assign_ai_post_defaults' ), 10, 3 );
    }

    public function add_admin_menu() {
        add_menu_page(
            'متحكم الذكاء الاصطناعي',
            'متحكم الـ AI',
            'manage_options',
            'wp-ai-controller',
            array( $this, 'render_admin_page' ),
            'dashicons-robot',
            80
        );
    }

    public function register_settings() {
        register_setting( 'wp_ai_settings_group', 'wp_ai_api_url' );
        register_setting( 'wp_ai_settings_group', 'wp_ai_token' );
        register_setting( 'wp_ai_settings_group', 'wp_ai_username' );
        
        register_setting( 'wp_ai_settings_group', 'wp_ai_default_author' );
        register_setting( 'wp_ai_settings_group', 'wp_ai_default_categories' );
    }

    /**
     * Intercepts REST API post creation.
     * If the post is created by the configured AI API user, it assigns the default author and categories.
     */
    public function assign_ai_post_defaults( $post, $request, $creating ) {
        if ( ! $creating ) {
            return;
        }

        $current_user = wp_get_current_user();
        $api_username = get_option( 'wp_ai_username' );

        if ( $current_user && $current_user->user_login === $api_username ) {
            $default_author = get_option( 'wp_ai_default_author' );
            $default_categories = get_option( 'wp_ai_default_categories' );

            $update_data = array( 'ID' => $post->ID );

            if ( ! empty( $default_author ) ) {
                $update_data['post_author'] = intval( $default_author );
            }

            // Temporarily remove action to prevent recursion
            remove_action( 'rest_insert_post', array( $this, 'assign_ai_post_defaults' ), 10 );
            
            wp_update_post( $update_data );
            
            if ( ! empty( $default_categories ) && is_array( $default_categories ) ) {
                wp_set_post_categories( $post->ID, $default_categories );
            }

            add_action( 'rest_insert_post', array( $this, 'assign_ai_post_defaults' ), 10, 3 );
        }
    }

    private function get_django_token() {
        return get_option( 'wp_ai_token' );
    }

    private function fetch_django_settings( $token ) {
        $api_url = get_option( 'wp_ai_api_url' );
        $settings_url = rtrim( $api_url, '/' ) . '/api/ai-settings/';

        $response = wp_remote_get( $settings_url, array(
            'headers' => array(
                'Authorization' => 'Bearer ' . $token,
                'Content-Type'  => 'application/json'
            ),
            'timeout' => 15
        ) );

        if ( is_wp_error( $response ) ) {
            return false;
        }

        return json_decode( wp_remote_retrieve_body( $response ), true );
    }

    private function save_django_settings( $token, $data ) {
        $api_url = get_option( 'wp_ai_api_url' );
        $settings_url = rtrim( $api_url, '/' ) . '/api/ai-settings/';

        $response = wp_remote_post( $settings_url, array(
            'headers' => array(
                'Authorization' => 'Bearer ' . $token,
                'Content-Type'  => 'application/json'
            ),
            'body'    => json_encode( $data ),
            'timeout' => 15
        ) );

        if ( is_wp_error( $response ) ) {
            return false;
        }

        return json_decode( wp_remote_retrieve_body( $response ), true );
    }

    public function render_admin_page() {
        $token = $this->get_django_token();
        $django_settings = false;
        $error_message = '';

        // Load WordPress data locally
        $wp_categories = get_categories( array( 'hide_empty' => false ) );
        $wp_users = get_users( array( 'capability' => array('publish_posts') ) );

        if ( $_SERVER['REQUEST_METHOD'] === 'POST' && isset( $_POST['save_ai_config'] ) ) {
            // Save local WordPress options
            $selected_author = isset( $_POST['default_author_id'] ) ? intval( $_POST['default_author_id'] ) : 0;
            $selected_categories = isset( $_POST['categories'] ) ? array_map( 'intval', $_POST['categories'] ) : array();

            update_option( 'wp_ai_default_author', $selected_author );
            update_option( 'wp_ai_default_categories', $selected_categories );

            if ( $token ) {
                // Also update global settings in Django
                $post_data = array(
                    'is_active'        => isset( $_POST['is_active'] ) ? true : false,
                    'articles_per_day' => intval( $_POST['articles_per_day'] )
                );
                
                $result = $this->save_django_settings( $token, $post_data );
                if ( $result ) {
                    echo '<div class="notice notice-success is-dismissible"><p>تم حفظ وتحديث الإعدادات بنجاح في الموقع المحلي وفي خادم Django.</p></div>';
                } else {
                    echo '<div class="notice notice-warning is-dismissible"><p>تم حفظ إعدادات ووردبريس المحلية، ولكن تعذر تحديث خادم Django.</p></div>';
                }
            } else {
                echo '<div class="notice notice-success is-dismissible"><p>تم حفظ الإعدادات المحلية لووردبريس بنجاح.</p></div>';
            }
        }

        if ( $token ) {
            $django_settings = $this->fetch_django_settings( $token );
        }

        $saved_wp_author = get_option( 'wp_ai_default_author' );
        $saved_wp_categories = get_option( 'wp_ai_default_categories', array() );
        if ( ! is_array( $saved_wp_categories ) ) {
            $saved_wp_categories = array();
        }

        ?>
        <div class="wrap" dir="rtl">
            <h1 class="wp-heading-inline">لوحة تحكم إعدادات الذكاء الاصطناعي (AI)</h1>
            <hr class="wp-header-end">

            <div class="notice notice-info inline" style="max-width: 800px; margin-top: 15px; padding: 15px; border-right: 4px solid #00a0d2; background: #fff; box-shadow: 0 1px 1px 0 rgba(0,0,0,.1); border-radius: 4px;">
                <p style="font-size: 14px; margin: 0; font-weight: 600; color: #23282d;">
                    💡 هذا النظام لتوليد ونشر أخبار حقيقية تم تطويره وبرمجته بواسطة <strong>أحمد إبراهيم</strong> (<a href="tel:01099437596" style="text-decoration: none; color: #0073aa;">01099437596</a>).
                </p>
            </div>

            <!-- Credentials Block -->
            <div class="card" style="max-width: 800px; margin-top: 20px; padding: 20px;">
                <h2>إعدادات الاتصال بخادم النظام الأساسي (Django)</h2>
                <form method="post" action="options.php">
                    <?php settings_fields( 'wp_ai_settings_group' ); ?>
                    <table class="form-table">
                        <tr>
                            <th scope="row">رابط النظام الأساسي (Django URL)</th>
                            <td>
                                <input type="url" name="wp_ai_api_url" value="<?php echo esc_attr( get_option( 'wp_ai_api_url' ) ); ?>" class="regular-text" placeholder="http://127.0.0.1:8000" required />
                            </td>
                        </tr>
                        <tr>
                            <th scope="row">مفتاح الاتصال الخاص بالـ API (Django API Token)</th>
                            <td>
                                <input type="password" name="wp_ai_token" value="<?php echo esc_attr( get_option( 'wp_ai_token' ) ); ?>" class="regular-text" placeholder="am_..." required />
                                <p class="description">مفتاح الأمان المستخرج من صفحة الإعدادات في لوحة تحكم Django.</p>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row">اسم المستخدم في ووردبريس (WP Username)</th>
                            <td>
                                <input type="text" name="wp_ai_username" value="<?php echo esc_attr( get_option( 'wp_ai_username' ) ); ?>" class="regular-text" placeholder="اسم مستخدم المسؤول بالووردبريس" required />
                                <p class="description">اسم المستخدم الخاص بمدير ووردبريس هذا، ليتم تعيين الإعدادات الافتراضية للمقالات المنشورة بواسطته.</p>
                            </td>
                        </tr>
                    </table>
                    <?php submit_button( 'حفظ بيانات الاتصال' ); ?>
                </form>
            </div>

            <!-- AI Settings Form -->
            <div class="card" style="max-width: 800px; margin-top: 20px; padding: 20px; border-right: 4px solid #00a0d2;">
                <h2>إعدادات التوليد والنشر (بيانات موقع ووردبريس الحالي)</h2>
                <form method="post" action="">
                    <input type="hidden" name="save_ai_config" value="1" />
                    <table class="form-table">
                        <!-- Global parameters fetched/synchronized with Django -->
                        <?php if ( $django_settings ) : ?>
                            <tr>
                                <th scope="row">حالة نظام الـ AI (Django)</th>
                                <td>
                                    <label>
                                        <input type="checkbox" name="is_active" value="1" <?php checked( $django_settings['is_active'], true ); ?> />
                                        تفعيل وتشغيل عمليات النشر التلقائي
                                    </label>
                                </td>
                            </tr>
                            <tr>
                                <th scope="row">عدد الأخبار اليومي (Django)</th>
                                <td>
                                    <input type="number" name="articles_per_day" value="<?php echo esc_attr( $django_settings['articles_per_day'] ); ?>" min="1" class="small-text" required /> أخبار / يوم
                                </td>
                            </tr>
                        <?php else : ?>
                            <tr>
                                <td colspan="2"><div class="notice notice-warning inline"><p>ملاحظة: خادم Django غير متصل. الإعدادات التالية ستحفظ محلياً في ووردبريس فقط.</p></div></td>
                            </tr>
                        <?php endif; ?>

                        <!-- Local WordPress parameters -->
                        <tr>
                            <th scope="row">الكاتب الافتراضي للأخبار (ووردبريس)</th>
                            <td>
                                <select name="default_author_id" required>
                                    <option value="">-- اختر كاتب من أعضاء ووردبريس الحاليين --</option>
                                    <?php foreach ( $wp_users as $user ) : ?>
                                        <option value="<?php echo esc_attr( $user->ID ); ?>" <?php selected( $saved_wp_author, $user->ID ); ?>>
                                            <?php echo esc_html( $user->display_name . ' (' . $user->user_login . ')' ); ?>
                                        </option>
                                    <?php endforeach; ?>
                                </select>
                                <p class="description">الخبر المنشور سيتم تسجيله باسم الكاتب المختار هنا.</p>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row">أقسام النشر المستهدفة (ووردبريس)</th>
                            <td>
                                <p class="description" style="margin-bottom: 10px;">حدد الأقسام الحالية في موقع ووردبريس هذا ليتم إرسال الأخبار إليها:</p>
                                <div style="max-height: 200px; overflow-y: auto; background: #f9f9f9; padding: 10px; border: 1px solid #ccd0d4; border-radius: 4px;">
                                    <?php foreach ( $wp_categories as $cat ) : ?>
                                        <?php $is_checked = in_array( $cat->term_id, $saved_wp_categories ); ?>
                                        <label style="display: block; margin-bottom: 5px;">
                                            <input type="checkbox" name="categories[]" value="<?php echo esc_attr( $cat->term_id ); ?>" <?php checked( $is_checked, true ); ?> />
                                            <?php echo esc_html( $cat->name ); ?>
                                        </label>
                                    <?php endforeach; ?>
                                </div>
                            </td>
                        </tr>
                    </table>
                    <?php submit_button( 'حفظ وتحديث إعدادات النشر بالذكاء الاصطناعي' ); ?>
                </form>
            </div>
        </div>
        <?php
    }
}

new WP_AI_News_Controller();
