plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.pesatracker.sync"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.pesatracker.sync"
        minSdk = 23
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Reliable background sending with automatic retries when the server can't be reached.
    implementation("androidx.work:work-runtime-ktx:2.9.0")
}
