<?php
/**
 * Plugin Name: متحكم الأخبار بالذكاء الاصطناعي (AI News Controller)
 * Description: إضافة لربط موقع ووردبريس بنظام الجدولة والتوليد الآلي والتحكم في إعدادات النشر من لوحة التحكم.
 * Version: 1.1.0
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
    }

    /**
     * Intercepts REST API post creation.
     * If the post is created by the configured AI API user, assigns the default
     * author, then enriches the post's real category (already set by Django's
     * initial REST push) with any configured secondary categories, and marks
     * the real category as primary in Yoast.
     */
    public function assign_ai_post_defaults( $post, $request, $creating ) {
        if ( ! $creating ) {
            return;
        }

        $current_user = wp_get_current_user();
        $api_username = get_option( 'wp_ai_username' );

        if ( $current_user && $current_user->user_login === $api_username ) {
            $default_author = get_option( 'wp_ai_default_author' );

            $update_data = array( 'ID' => $post->ID );

            if ( ! empty( $default_author ) ) {
                $update_data['post_author'] = intval( $default_author );
            }

            // Temporarily remove action to prevent recursion
            remove_action( 'rest_insert_post', array( $this, 'assign_ai_post_defaults' ), 10 );

            wp_update_post( $update_data );

            $primary_secondary_map = get_option( 'wp_ai_primary_secondary_map', array() );
            if ( ! empty( $primary_secondary_map ) && is_array( $primary_secondary_map ) ) {
                // These are whatever category(ies) Django already assigned in its
                // initial POST - this never overrides them, only adds to them.
                $current_categories = wp_get_post_categories( $post->ID );
                $categories_to_add = array();
                $matched_primary_id = null;

                foreach ( $current_categories as $cat_id ) {
                    if ( isset( $primary_secondary_map[ $cat_id ] ) ) {
                        $matched_primary_id = $cat_id;
                        foreach ( (array) $primary_secondary_map[ $cat_id ] as $secondary_id ) {
                            $categories_to_add[] = intval( $secondary_id );
                        }
                    }
                }

                if ( $matched_primary_id ) {
                    update_post_meta( $post->ID, '_yoast_wpseo_primary_category', $matched_primary_id );
                }
                if ( ! empty( $categories_to_add ) ) {
                    $merged = array_unique( array_merge( $current_categories, $categories_to_add ) );
                    wp_set_post_categories( $post->ID, $merged );
                }
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

            // Build the primary -> [secondary, ...] map from the submitted form.
            $selected_primary = isset( $_POST['primary_categories'] ) ? array_map( 'intval', $_POST['primary_categories'] ) : array();
            $secondary_input = isset( $_POST['secondary_categories'] ) && is_array( $_POST['secondary_categories'] ) ? $_POST['secondary_categories'] : array();
            $primary_secondary_map = array();
            foreach ( $selected_primary as $primary_id ) {
                $secondaries = isset( $secondary_input[ $primary_id ] ) ? array_map( 'intval', (array) $secondary_input[ $primary_id ] ) : array();
                $primary_secondary_map[ $primary_id ] = $secondaries;
            }

            update_option( 'wp_ai_default_author', $selected_author );
            update_option( 'wp_ai_primary_secondary_map', $primary_secondary_map );

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
        $saved_primary_secondary_map = get_option( 'wp_ai_primary_secondary_map', array() );
        if ( ! is_array( $saved_primary_secondary_map ) ) {
            $saved_primary_secondary_map = array();
        }
        $saved_primary_categories = array_keys( $saved_primary_secondary_map );

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
                            <th scope="row">الأقسام الأساسية وربطها بأقسام فرعية (ووردبريس)</th>
                            <td>
                                <p class="description" style="margin-bottom: 10px;">
                                    حدد أي الأقسام يجب اعتبارها "أساسية". كل خبر يبقى منشوراً تحت قسمه الحقيقي الواحد الذي يحدده النظام تلقائياً حسب موضوعه؛
                                    لكن إن كان ذلك القسم محدداً هنا كأساسي، يمكنك أيضاً اختيار قسم أو أكثر "فرعي" يُضاف تلقائياً معه (مثال: اجعل "الرئيسية" فرعياً لكل من "أسعار" و"خدمات" و"ترند").
                                </p>
                                <div style="max-height: 400px; overflow-y: auto; background: #f9f9f9; padding: 10px; border: 1px solid #ccd0d4; border-radius: 4px;">
                                    <?php foreach ( $wp_categories as $cat ) : ?>
                                        <?php
                                        $is_primary = in_array( $cat->term_id, $saved_primary_categories );
                                        $secondary_selected = isset( $saved_primary_secondary_map[ $cat->term_id ] ) ? (array) $saved_primary_secondary_map[ $cat->term_id ] : array();
                                        ?>
                                        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #eee;">
                                            <label style="min-width: 200px; font-weight: 600;">
                                                <input type="checkbox" name="primary_categories[]" value="<?php echo esc_attr( $cat->term_id ); ?>" <?php checked( $is_primary, true ); ?> />
                                                <?php echo esc_html( $cat->name ); ?>
                                            </label>
                                            <span style="color: #888;">← أضف كقسم فرعي:</span>
                                            <select name="secondary_categories[<?php echo esc_attr( $cat->term_id ); ?>][]" multiple style="min-width: 220px; height: 60px;">
                                                <?php foreach ( $wp_categories as $sub_cat ) : ?>
                                                    <?php if ( $sub_cat->term_id === $cat->term_id ) continue; ?>
                                                    <option value="<?php echo esc_attr( $sub_cat->term_id ); ?>" <?php selected( in_array( $sub_cat->term_id, $secondary_selected ), true ); ?>>
                                                        <?php echo esc_html( $sub_cat->name ); ?>
                                                    </option>
                                                <?php endforeach; ?>
                                            </select>
                                        </div>
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
