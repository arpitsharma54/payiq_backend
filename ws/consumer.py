import json
from channels.generic.websocket import AsyncWebsocketConsumer


class TaskStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = "task_status_updates"
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def task_update(self, event):
        response = {
            "status": event["status"],
            "message": event.get("message", "")
        }
        if "merchant_id" in event:
            response["merchant_id"] = event["merchant_id"]
        if "bank_account_id" in event:
            response["bank_account_id"] = event["bank_account_id"]
        
        await self.send(json.dumps(response))
