return {
    LrSdkVersion = 6.0,
    LrSdkMinimumVersion = 3.0,

    LrToolkitIdentifier = "com.sdierauf.lightroom-flatfield-stager",
    LrPluginName = "Flat-Field Stager",

    LrPluginInfoProvider = "PluginInfoProvider.lua",

    LrLibraryMenuItems = {
        {
            title = "Stage Flat-Field Calibration Frame...",
            file = "StageFlatField.lua",
            enabledWhen = "photosSelected",
        },
        {
            title = "Apply Flat-Field With Python Pipeline...",
            file = "ApplyPythonFlatField.lua",
            enabledWhen = "photosSelected",
        },
        {
            title = "Configure Flat-Field Stager...",
            file = "Configure.lua",
        },
    },

    VERSION = {
        major = 0,
        minor = 1,
        revision = 0,
        build = 1,
    },
}
