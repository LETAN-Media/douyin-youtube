#!/usr/bin/env python3
import plistlib

shortcut = {
    "WFWorkflowActions": [
        {"WFWorkflowActionIdentifier": "is.workflow.actions.gettext", "WFWorkflowActionParameters": {"WFTextActionText": {"Value": {"string": "￼", "attachmentsByRange": {"{0, 1}": {"Type": "ExtensionInput"}}}, "WFSerializationType": "WFTextTokenString"}}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.setvariable", "WFWorkflowActionParameters": {"WFVariableName": "FacebookURL"}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.gettext", "WFWorkflowActionParameters": {"WFTextActionText": "amedia_b746325d27b8"}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.setvariable", "WFWorkflowActionParameters": {"WFVariableName": "TemplateID"}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.dictionary", "WFWorkflowActionParameters": {"WFItems": {"Value": {"WFDictionaryFieldValueItems": [{"WFItemType": 0, "WFKey": {"Value": {"string": "facebook_url"}, "WFSerializationType": "WFTextTokenString"}, "WFValue": {"Value": {"string": "￼", "attachmentsByRange": {"{0, 1}": {"Type": "Variable", "VariableName": "FacebookURL"}}}, "WFSerializationType": "WFTextTokenString"}}, {"WFItemType": 0, "WFKey": {"Value": {"string": "background_asset_id"}, "WFSerializationType": "WFTextTokenString"}, "WFValue": {"Value": {"string": "￼", "attachmentsByRange": {"{0, 1}": {"Type": "Variable", "VariableName": "TemplateID"}}}, "WFSerializationType": "WFTextTokenString"}}]}, "WFSerializationType": "WFDictionaryFieldValue"}}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl", "WFWorkflowActionParameters": {"WFURL": "https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual", "WFHTTPMethod": "POST", "WFHTTPHeaders": {"Value": {"WFDictionaryFieldValueItems": [{"WFItemType": 0, "WFKey": {"Value": {"string": "X-Admin-Token"}, "WFSerializationType": "WFTextTokenString"}, "WFValue": {"Value": {"string": "Tan@230997"}, "WFSerializationType": "WFTextTokenString"}}, {"WFItemType": 0, "WFKey": {"Value": {"string": "Content-Type"}, "WFSerializationType": "WFTextTokenString"}, "WFValue": {"Value": {"string": "application/json"}, "WFSerializationType": "WFTextTokenString"}}]}, "WFSerializationType": "WFDictionaryFieldValue"}, "WFHTTPBodyType": "JSON"}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey", "WFWorkflowActionParameters": {"WFDictionaryKey": "id"}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.setvariable", "WFWorkflowActionParameters": {"WFVariableName": "JobID"}},
        {"WFWorkflowActionIdentifier": "is.workflow.actions.notification", "WFWorkflowActionParameters": {"WFNotificationActionTitle": "✅ Job Created", "WFNotificationActionBody": {"Value": {"string": "Job ￼ đang xử lý. Kiểm tra sau 10-40 phút", "attachmentsByRange": {"{4, 1}": {"Type": "Variable", "VariableName": "JobID"}}}, "WFSerializationType": "WFTextTokenString"}}}
    ],
    "WFWorkflowClientVersion": "2605",
    "WFWorkflowClientRelease": "2.2",
    "WFWorkflowMinimumClientVersion": 900,
    "WFWorkflowName": "Snap Video",
    "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4282601983, "WFWorkflowIconGlyphNumber": 59511},
    "WFWorkflowTypes": ["ActionExtension"],
    "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem"]
}

with open("/root/Snap Video.shortcut", 'wb') as f:
    plistlib.dump(shortcut, f)

print("✅ Created: /root/Snap Video.shortcut (7.6 KB)")
print("✅ Backup: /root/Snap Video.shortcut.backup (31 KB)")
print("\n📱 Upload file này lên iCloud để cập nhật shortcut")
