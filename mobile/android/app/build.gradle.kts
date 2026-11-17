plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

val staged = providers.gradleProperty("solasiStage").orNull
    ?: throw GradleException("Stage the app first and supply -PsolasiStage=<absolute staging directory>")
val pythonBuild = providers.gradleProperty("solasiPython").orNull
    ?: throw GradleException("Supply -PsolasiPython=<Python 3.13 executable>")

android {
    namespace = "app.solasi.mobile"
    compileSdk = 36
    defaultConfig {
        applicationId = "app.solasi.mobile"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0-mobile-dev"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    sourceSets.getByName("main").assets.srcDir(file("$staged/frontend"))
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        buildPython(pythonBuild)
        pip {
            options("--extra-index-url", "https://pypi.flet.dev")
            install("-r", rootProject.file("../requirements-mobile.lock").absolutePath)
        }
    }
    sourceSets.getByName("main").srcDir(file("$staged/python"))
}

dependencies {
    implementation("androidx.webkit:webkit:1.14.0")
    testImplementation("junit:junit:4.13.2")
}
