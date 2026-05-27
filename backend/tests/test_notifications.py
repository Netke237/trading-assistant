# backend/tests/test_notifications.py
from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestGmail:
    @pytest.mark.asyncio
    async def test_gmail_send_called_with_correct_params(self):
        from app.services.notifications.gmail import send_gmail
        with patch('app.services.notifications.gmail.smtplib.SMTP_SSL') as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server
            await send_gmail(
                to='test@example.com', subject='Test', body='Body',
                smtp_host='smtp.gmail.com', smtp_port=465,
                smtp_user='user@gmail.com', smtp_password='app-pass',
            )
            mock_server.login.assert_called_once_with('user@gmail.com', 'app-pass')
            mock_server.send_message.assert_called_once()
            sent_msg = mock_server.send_message.call_args[0][0]
            assert sent_msg['Subject'] == 'Test'
            assert sent_msg['To'] == 'test@example.com'

    @pytest.mark.asyncio
    async def test_gmail_skips_when_not_configured(self):
        from app.services.notifications.gmail import send_gmail
        with patch('app.services.notifications.gmail.smtplib.SMTP_SSL') as mock_smtp:
            await send_gmail(to='', subject='Test', body='Test', smtp_user='', smtp_password='')
            mock_smtp.assert_not_called()


class TestTelegram:
    @pytest.mark.asyncio
    async def test_telegram_send_called_with_correct_params(self):
        from app.services.notifications.telegram import send_telegram
        with patch('app.services.notifications.telegram.httpx.AsyncClient') as mock_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_client
            await send_telegram(bot_token='123:abc', chat_id='456', text='<b>Alert</b>')
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert '123:abc' in call_args[0][0]
            assert call_args[1]['json']['chat_id'] == '456'

    @pytest.mark.asyncio
    async def test_telegram_skips_when_not_configured(self):
        from app.services.notifications.telegram import send_telegram
        with patch('app.services.notifications.telegram.httpx.AsyncClient') as mock_cls:
            await send_telegram(bot_token='', chat_id='', text='test')
            mock_cls.assert_not_called()


class TestQueue:
    @pytest.mark.asyncio
    async def test_queue_drops_when_full_not_raises(self):
        from app.services.notifications.queue import _NOTIFY_QUEUE, enqueue
        _NOTIFY_QUEUE._queue.clear()
        for i in range(500):
            _NOTIFY_QUEUE.put_nowait({'channel': 'gmail', 'params': {}})
        await enqueue('gmail', {'to': 'x@x.com'})
        assert _NOTIFY_QUEUE.qsize() == 500
        _NOTIFY_QUEUE._queue.clear()
