local LrApplication = import "LrApplication"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFileUtils = import "LrFileUtils"
local LrFunctionContext = import "LrFunctionContext"
local LrPathUtils = import "LrPathUtils"
local LrProgressScope = import "LrProgressScope"
local LrTasks = import "LrTasks"
local LrView = import "LrView"

local Settings = require "Settings"
local bind = LrView.bind

local function trim(value)
    if value == nil then
        return ""
    end

    return tostring(value):match("^%s*(.-)%s*$")
end

local function isWindows()
    if package and package.config and package.config:sub(1, 1) == "\\" then
        return true
    end

    local pluginPath = (_PLUGIN and _PLUGIN.path) or ""
    return pluginPath:match("^%a:[/\\]") ~= nil or pluginPath:find("\\", 1, true) ~= nil
end

local function shellQuote(arg)
    arg = tostring(arg or "")

    if isWindows() then
        return '"' .. arg:gsub('"', '\\"') .. '"'
    end

    return "'" .. arg:gsub("'", "'\\''") .. "'"
end

local function commandPrefix(command)
    command = trim(command)

    if command == "" then
        command = Settings.defaultPythonCommand()
    end

    if command:find("/", 1, true) or command:find("\\", 1, true) or command:match("^%a:") then
        return shellQuote(command)
    end

    return command
end

local function writeTextFile(path, text)
    local file, err = io.open(path, "wb")
    if not file then
        return nil, err
    end

    file:write(text)
    file:close()
    return true
end

local function readTextFile(path)
    local file = io.open(path, "rb")
    if not file then
        return nil
    end

    local text = file:read("*a")
    file:close()
    return text
end

local function readLines(path)
    local lines = {}
    local text = readTextFile(path) or ""

    for line in text:gmatch("[^\r\n]+") do
        if trim(line) ~= "" then
            table.insert(lines, line)
        end
    end

    return lines
end

local function fileExists(path)
    local exists = LrFileUtils.exists(path)
    return exists == true or exists == "file"
end

local function urlDecode(value)
    value = tostring(value or "")
    value = value:gsub("+", " ")
    return (value:gsub("%%(%x%x)", function(hex)
        return string.char(tonumber(hex, 16))
    end))
end

local function parseResult(text)
    local result = {}

    for line in tostring(text or ""):gmatch("[^\r\n]+") do
        local key, value = line:match("^([^=]+)=(.*)$")
        if key then
            result[key] = urlDecode(value)
        end
    end

    return result
end

local function tempPath(suffix)
    local tempDir = LrPathUtils.getStandardFilePath("temp")
    local name = "ffcplugin-" .. tostring(os.time()) .. "-" .. tostring(math.random(100000, 999999)) .. suffix
    return LrPathUtils.child(tempDir, name)
end

local function chooseCalibrationPath()
    local result = LrDialogs.runOpenPanel {
        title = "Choose flat-field calibration raw",
        prompt = "Choose",
        canChooseFiles = true,
        canChooseDirectories = false,
        allowsMultipleSelection = false,
    }

    if result and result[1] then
        return result[1]
    end

    return nil
end

local function getPhotoPath(photo)
    local ok, path = LrTasks.pcall(function()
        return photo:getRawMetadata("path")
    end)

    if ok and path and path ~= "" then
        return path
    end

    return nil
end

local function getSelectedPhotos(catalog)
    local activePhoto = catalog:getTargetPhoto()
    if not activePhoto then
        return {}
    end

    local photos = catalog:getTargetPhotos()

    if not photos or #photos == 0 then
        photos = { activePhoto }
    end

    return photos or {}
end

local function getPhotoPaths(photos)
    local paths = {}

    for _, photo in ipairs(photos) do
        local path = getPhotoPath(photo)
        if path then
            table.insert(paths, path)
        end
    end

    return paths
end

local function chooseCalibration(catalog, photos)
    local activePhoto = catalog:getTargetPhoto()
    local activePath = activePhoto and getPhotoPath(activePhoto)

    if activePath then
        local choice = LrDialogs.confirm(
            "Choose calibration source",
            "Use the active selected photo as the flat-field calibration frame, or choose a raw file from disk.",
            "Use Active Photo",
            "Choose File",
            "Cancel"
        )

        if choice == "ok" then
            local scanPhotos = {}
            for _, photo in ipairs(photos) do
                if photo ~= activePhoto then
                    table.insert(scanPhotos, photo)
                end
            end
            if #scanPhotos == 0 then
                error("When using the active selected photo as the calibration frame, select at least one scan photo too.", 0)
            end
            return activePath, scanPhotos, activePhoto
        elseif choice == "other" then
            return nil, nil, nil
        end
    end

    local calibrationPath = chooseCalibrationPath()
    if not calibrationPath then
        return nil, nil, nil
    end

    return calibrationPath, photos, nil
end

local function cropValue(settings, key, defaultValue)
    local value = settings and settings[key]
    if value == nil then
        return defaultValue
    end
    return value
end

local function getDevelopCrop(photo)
    local ok, settings = LrTasks.pcall(function()
        return photo:getDevelopSettings()
    end)

    if not ok or not settings then
        return nil
    end

    return {
        left = cropValue(settings, "CropLeft", 0),
        top = cropValue(settings, "CropTop", 0),
        right = cropValue(settings, "CropRight", 1),
        bottom = cropValue(settings, "CropBottom", 1),
        angle = cropValue(settings, "CropAngle", 0),
        orientation = cropValue(settings, "orientation", "AB"),
    }
end

local function cropLine(path, crop)
    return table.concat({
        path,
        tostring(crop.left),
        tostring(crop.top),
        tostring(crop.right),
        tostring(crop.bottom),
        tostring(crop.angle),
        tostring(crop.orientation),
    }, "\t")
end

local function writeCropList(path, photos, calibrationPhoto)
    local lines = {}
    local seen = {}

    for _, photo in ipairs(photos) do
        local photoPath = getPhotoPath(photo)
        local crop = getDevelopCrop(photo)
        if photoPath and crop then
            table.insert(lines, cropLine(photoPath, crop))
            seen[photoPath] = true
        end
    end

    if calibrationPhoto then
        local calibrationPath = getPhotoPath(calibrationPhoto)
        if calibrationPath and not seen[calibrationPath] then
            local crop = getDevelopCrop(calibrationPhoto)
            if crop then
                table.insert(lines, cropLine(calibrationPath, crop))
            end
        end
    end

    return writeTextFile(path, table.concat(lines, "\n") .. "\n")
end

local function splitTabs(line)
    local parts = {}
    for part in (tostring(line or "") .. "\t"):gmatch("(.-)\t") do
        table.insert(parts, part)
    end
    return parts
end

local function readCropFile(path)
    local crops = {}
    local text = readTextFile(path) or ""

    for line in text:gmatch("[^\r\n]+") do
        local parts = splitTabs(line)
        if #parts >= 6 then
            crops[parts[1]] = {
                left = tonumber(parts[2]) or 0,
                top = tonumber(parts[3]) or 0,
                right = tonumber(parts[4]) or 1,
                bottom = tonumber(parts[5]) or 1,
                angle = tonumber(parts[6]) or 0,
            }
        end
    end

    return crops
end

local function addOptional(parts, flag, value)
    if trim(value) ~= "" then
        table.insert(parts, flag)
        table.insert(parts, shellQuote(value))
    end
end

local function truthy(value)
    value = trim(value):lower()
    return value == "1" or value == "true" or value == "yes" or value == "on"
end

local function chooseApplyOptions(settings)
    local chosenSettings = nil

    LrFunctionContext.callWithContext("PythonFlatFieldApplyOptions", function(context)
        local f = LrView.osFactory()
        local properties = LrBinding.makePropertyTable(context)
        properties.attemptDustCorrection = truthy(settings.dustCorrection)

        local contents = f:column {
            bind_to_object = properties,
            spacing = f:control_spacing(),

            f:checkbox {
                title = "Attempt dust correction",
                value = bind "attemptDustCorrection",
            },
        }

        local result = LrDialogs.presentModalDialog {
            title = "Python Flat-Field Options",
            contents = contents,
            actionVerb = "Apply",
        }

        if result == "ok" then
            settings.dustCorrection = properties.attemptDustCorrection and "true" or "false"
            Settings.saveApplyOptions {
                dustCorrection = settings.dustCorrection,
            }
            chosenSettings = settings
        end
    end)

    return chosenSettings
end

local function fail(message)
    error(message, 0)
end

local function buildCommand(settings, calibrationPath, selectedListPath, cropListPath, outputListPath, outputCropListPath, resultPath, progressPath)
    local parts = {
        commandPrefix(settings.pythonCommand),
        shellQuote(settings.applyScriptPath),
        "--calibration",
        shellQuote(calibrationPath),
        "--selected-list",
        shellQuote(selectedListPath),
        "--crop-list",
        shellQuote(cropListPath),
        "--output-list",
        shellQuote(outputListPath),
        "--output-crop-list",
        shellQuote(outputCropListPath),
        "--result-file",
        shellQuote(resultPath),
        "--progress-file",
        shellQuote(progressPath),
        "--output-subdir",
        shellQuote(settings.outputSubfolder),
        "--backend",
        shellQuote(settings.backend),
        "--compressor",
        shellQuote(settings.compressor),
        "--compression",
        shellQuote(settings.compression),
        "--smooth-sigma",
        shellQuote(settings.smoothSigma),
        "--norm-percentile",
        shellQuote(settings.normPercentile),
        "--dust-sigma",
        shellQuote(settings.dustSigma),
        "--dust-threshold",
        shellQuote(settings.dustThreshold),
        "--dust-amount",
        shellQuote(settings.dustAmount),
        "--dust-max-gain",
        shellQuote(settings.dustMaxGain),
    }

    if truthy(settings.dustCorrection) then
        table.insert(parts, "--dust-correction")
    end

    addOptional(parts, "--dnglab", settings.dnglabPath)
    addOptional(parts, "--dng-converter", settings.dngConverterPath)

    return table.concat(parts, " ")
end

local function writeLauncherScript(scriptPath, command, resultPath, logPath)
    local script

    if isWindows() then
        script = table.concat({
            "@echo off",
            command .. " > " .. shellQuote(logPath) .. " 2>&1",
            "if errorlevel 1 if not exist " .. shellQuote(resultPath) .. " (",
            "  echo status=error>" .. shellQuote(resultPath),
            "  echo message=Python helper exited before writing a result file. See " .. logPath .. ".>>" .. shellQuote(resultPath),
            ")",
            "",
        }, "\r\n")
    else
        script = table.concat({
            "#!/bin/sh",
            command .. " > " .. shellQuote(logPath) .. " 2>&1",
            "code=$?",
            "if [ \"$code\" -ne 0 ] && [ ! -s " .. shellQuote(resultPath) .. " ]; then",
            "  {",
            "    printf '%s\\n' 'status=error'",
            "    printf '%s\\n' 'message=Python helper exited before writing a result file. See " .. logPath .. ".'",
            "  } > " .. shellQuote(resultPath),
            "fi",
            "",
        }, "\n")
    end

    return writeTextFile(scriptPath, script)
end

local function updateProgress(progressScope, progressPath, fallbackCaption)
    local progress = parseResult(readTextFile(progressPath))
    local caption = trim(progress.caption) ~= "" and progress.caption or fallbackCaption
    local current = tonumber(progress.current)
    local total = tonumber(progress.total)

    LrTasks.pcall(function()
        progressScope:setCaption(caption)
    end)

    if current and total and total > 0 then
        LrTasks.pcall(function()
            progressScope:setPortionComplete(current, total)
        end)
    end
end

local function launchAndPoll(command, resultPath, progressPath, scriptPath, logPath, progressScope, fallbackCaption)
    local wrote, writeErr = writeLauncherScript(scriptPath, command, resultPath, logPath)
    if not wrote then
        fail("Could not write launcher script: " .. tostring(writeErr))
    end

    local launcher
    if isWindows() then
        launcher = "start \"\" /B cmd /C " .. shellQuote(scriptPath)
    else
        launcher = "/bin/sh " .. shellQuote(scriptPath) .. " &"
    end

    local launchExitCode = LrTasks.execute(launcher)
    if launchExitCode ~= 0 then
        fail("Could not launch the Python flat-field helper.")
    end

    updateProgress(progressScope, progressPath, fallbackCaption)
    while not fileExists(resultPath) do
        LrTasks.sleep(0.25)
        updateProgress(progressScope, progressPath, fallbackCaption)
    end
    updateProgress(progressScope, progressPath, fallbackCaption)
end

local function importOutputs(catalog, outputPaths)
    local imported = {}
    local err = nil

    local ok = LrTasks.pcall(function()
        catalog:withWriteAccessDo("Import Python flat-field DNGs", function()
            for _, path in ipairs(outputPaths) do
                local photo = catalog:findPhotoByPath(path)
                if not photo then
                    photo = catalog:addPhoto(path)
                end
                if photo then
                    table.insert(imported, photo)
                end
            end
        end)
    end)

    if not ok then
        err = "Lightroom could not import one or more generated DNGs."
    end

    return imported, err
end

local function applyOutputCrops(catalog, outputPaths, importedPhotos, cropListPath)
    local crops = readCropFile(cropListPath)
    local hasCrops = false
    for _ in pairs(crops) do
        hasCrops = true
        break
    end

    if not hasCrops then
        return nil
    end

    local ok = LrTasks.pcall(function()
        catalog:withWriteAccessDo("Apply Python flat-field crop settings", function()
            for index, photo in ipairs(importedPhotos) do
                local crop = crops[outputPaths[index]]
                if crop then
                    photo:applyDevelopSettings({
                        CropLeft = crop.left,
                        CropTop = crop.top,
                        CropRight = crop.right,
                        CropBottom = crop.bottom,
                        CropAngle = crop.angle,
                    })
                end
            end
        end)
    end)

    if not ok then
        return "The DNGs were imported, but Lightroom could not apply the matching crop settings."
    end

    return nil
end

local function selectPhotos(catalog, photos)
    if #photos == 0 then
        return
    end

    local active = photos[1]
    local others = {}
    for index = 2, #photos do
        table.insert(others, photos[index])
    end

    catalog:setSelectedPhotos(active, others)
end

local function cleanup(paths)
    for _, path in ipairs(paths) do
        if path then
            LrTasks.pcall(function()
                LrFileUtils.delete(path)
            end)
        end
    end
end

local function run()
    local tempFiles = {}
    local progressScope = LrProgressScope {
        title = "Python flat-field correction",
    }

    local ok, err = LrTasks.pcall(function()
        progressScope:setCaption("Preparing selected photos")
        progressScope:setPortionComplete(0, 1)
        local catalog = LrApplication.activeCatalog()
        local photos = getSelectedPhotos(catalog)

        if #photos == 0 then
            fail("Select one or more raw scan photos before running the Python flat-field pipeline.")
        end

        local calibrationPath, scanPhotos, calibrationPhoto = chooseCalibration(catalog, photos)
        if not calibrationPath then
            return
        end

        local photoPaths = getPhotoPaths(scanPhotos)
        if #photoPaths == 0 then
            fail("Lightroom did not provide filesystem paths for the selected photos.")
        end

        local settings = Settings.effective()
        if not Settings.pathExists(settings.applyScriptPath) then
            fail("The Python apply helper was not found:\n\n" .. settings.applyScriptPath .. "\n\nOpen Flat Field Correction... and choose Configure to choose scripts/run_ffc_apply.py.")
        end

        settings = chooseApplyOptions(settings)
        if not settings then
            return
        end

        local selectedListPath = tempPath("-selected.txt")
        local cropListPath = tempPath("-crops.txt")
        local outputListPath = tempPath("-outputs.txt")
        local outputCropListPath = tempPath("-output-crops.txt")
        local resultPath = tempPath("-result.txt")
        local progressPath = tempPath("-progress.txt")
        local launcherPath = tempPath(isWindows() and "-helper.cmd" or "-helper.sh")
        local logPath = tempPath("-helper.log")
        table.insert(tempFiles, selectedListPath)
        table.insert(tempFiles, cropListPath)
        table.insert(tempFiles, outputListPath)
        table.insert(tempFiles, outputCropListPath)
        table.insert(tempFiles, resultPath)
        table.insert(tempFiles, progressPath)
        table.insert(tempFiles, launcherPath)

        local wrote, writeErr = writeTextFile(selectedListPath, table.concat(photoPaths, "\n") .. "\n")
        if not wrote then
            fail("Could not write selected-photo list: " .. tostring(writeErr))
        end

        local wroteCrops, cropErr = writeCropList(cropListPath, scanPhotos, calibrationPhoto)
        if not wroteCrops then
            fail("Could not write crop list: " .. tostring(cropErr))
        end

        local command = buildCommand(settings, calibrationPath, selectedListPath, cropListPath, outputListPath, outputCropListPath, resultPath, progressPath)
        launchAndPoll(command, resultPath, progressPath, launcherPath, logPath, progressScope, "Running Python flat-field helper")
        local result = parseResult(readTextFile(resultPath))

        if result.status ~= "ok" then
            fail(result.message ~= "" and result.message or "The Python flat-field helper failed.")
        end
        LrTasks.pcall(function()
            LrFileUtils.delete(logPath)
        end)

        progressScope:setCaption("Importing corrected DNGs into Lightroom")
        progressScope:setPortionComplete(0, 1)
        local outputPaths = readLines(outputListPath)
        if #outputPaths == 0 then
            fail("The Python flat-field helper did not report any output DNGs.")
        end

        local imported, importErr = importOutputs(catalog, outputPaths)
        if #imported == 0 then
            fail("The DNGs were generated, but Lightroom could not import them:\n\n" .. tostring(importErr))
        end

        local cropWarning = applyOutputCrops(catalog, outputPaths, imported, outputCropListPath)
        selectPhotos(catalog, imported)
        progressScope:setCaption("Python flat-field correction complete")
        progressScope:setPortionComplete(1, 1)

        local warning = trim(result.warning)
        if cropWarning then
            warning = trim(warning .. "\n" .. cropWarning)
        end
        local message = "Generated and imported " .. tostring(#imported) .. " flat-field corrected DNGs in:\n" .. tostring(result.output_dir)
        local style = "info"
        if warning ~= "" then
            message = message .. "\n\nWarning: " .. warning
            style = "warning"
        end

        LrDialogs.message("Python flat-field correction complete", message, style)
    end)

    cleanup(tempFiles)
    LrTasks.pcall(function()
        progressScope:done()
    end)

    if not ok then
        LrDialogs.message("Python Flat-Field Pipeline", tostring(err), "critical")
    end
end

local ApplyPythonFlatField = {}

function ApplyPythonFlatField.run()
    run()
end

function ApplyPythonFlatField.start()
    LrTasks.startAsyncTask(run, "Apply Flat-Field With Python Pipeline")
end

return ApplyPythonFlatField
