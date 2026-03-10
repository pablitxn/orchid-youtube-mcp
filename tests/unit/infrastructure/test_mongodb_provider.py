"""Unit tests for DocumentStoreAdapter.

These tests verify the ID mapping behavior between domain model 'id'
and MongoDB's '_id' field via the commons adapter.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from bson import ObjectId

from src.infrastructure.adapters.document import DocumentStoreAdapter


class TestDocumentStoreAdapter:
    """Tests for DocumentStoreAdapter.

    These tests verify the ID mapping behavior between domain model 'id'
    and MongoDB's '_id' field.
    """

    @pytest.fixture
    def mock_resource(self):
        """Create a mock commons MongoDB resource."""
        resource = MagicMock()
        resource.insert_one = AsyncMock()
        resource.find_one = AsyncMock()
        resource.update_one = AsyncMock()
        resource.delete_one = AsyncMock()
        resource.count = AsyncMock()
        resource.health_check = AsyncMock()
        resource.close = AsyncMock()

        mock_collection = MagicMock()
        resource.collection = MagicMock(return_value=mock_collection)

        return {"resource": resource, "collection": mock_collection}

    @pytest.fixture
    def adapter(self, mock_resource):
        """Create DocumentStoreAdapter with mocked resource."""
        return DocumentStoreAdapter(mock_resource["resource"])

    # =========================================================================
    # Insert Tests
    # =========================================================================

    async def test_insert_uses_id_as_mongodb_id(self, adapter, mock_resource):
        """Test that insert uses document 'id' as MongoDB '_id'."""
        mock_resource["resource"].insert_one.return_value = "test-uuid-123"

        document = {
            "id": "test-uuid-123",
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }

        result = await adapter.insert("videos", document)

        # Verify the document was transformed
        call_args = mock_resource["resource"].insert_one.call_args
        inserted_doc = call_args[0][1]
        assert "_id" in inserted_doc
        assert inserted_doc["_id"] == "test-uuid-123"
        assert "id" not in inserted_doc

        assert result == "test-uuid-123"

    async def test_insert_does_not_modify_original_document(
        self, adapter, mock_resource
    ):
        """Test that insert doesn't modify the original document."""
        mock_resource["resource"].insert_one.return_value = "test-uuid"

        original_document = {
            "id": "test-uuid",
            "title": "Test",
        }

        await adapter.insert("videos", original_document)

        # Original document should be unchanged
        assert "id" in original_document
        assert "_id" not in original_document

    # =========================================================================
    # Insert Many Tests
    # =========================================================================

    async def test_insert_many_uses_id_as_mongodb_id(self, adapter, mock_resource):
        """Test that insert_many uses document 'id' as MongoDB '_id'."""
        mock_resource["collection"].insert_many = AsyncMock(
            return_value=MagicMock(inserted_ids=["uuid-1", "uuid-2"])
        )

        documents = [
            {"id": "uuid-1", "title": "Video 1"},
            {"id": "uuid-2", "title": "Video 2"},
        ]

        result = await adapter.insert_many("videos", documents)

        # Verify all documents were transformed
        call_args = mock_resource["collection"].insert_many.call_args[0][0]
        assert len(call_args) == 2
        assert all("_id" in doc for doc in call_args)
        assert all("id" not in doc for doc in call_args)
        assert call_args[0]["_id"] == "uuid-1"
        assert call_args[1]["_id"] == "uuid-2"

        assert result == ["uuid-1", "uuid-2"]

    async def test_insert_many_empty_list(self, adapter, mock_resource):
        """Test insert_many with empty list."""
        result = await adapter.insert_many("videos", [])
        assert result == []

    # =========================================================================
    # Find By ID Tests
    # =========================================================================

    async def test_find_by_id_with_uuid_string(self, adapter, mock_resource):
        """Test find_by_id with UUID string ID."""
        mock_resource["resource"].find_one.return_value = {
            "_id": "test-uuid-123",
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }

        result = await adapter.find_by_id("videos", "test-uuid-123")

        # Should search by string _id first
        mock_resource["resource"].find_one.assert_called_with(
            "videos", {"_id": "test-uuid-123"}
        )

        # Result should have 'id' instead of '_id'
        assert result is not None
        assert "id" in result
        assert result["id"] == "test-uuid-123"
        assert "_id" not in result

    async def test_find_by_id_falls_back_to_objectid(self, adapter, mock_resource):
        """Test find_by_id falls back to ObjectId for legacy documents."""
        object_id = ObjectId()

        # First call returns None (string ID not found)
        # Second call returns document (found by ObjectId)
        mock_resource["resource"].find_one.side_effect = [
            None,
            {
                "_id": object_id,
                "youtube_id": "dQw4w9WgXcQ",
                "title": "Legacy Video",
            },
        ]

        result = await adapter.find_by_id("videos", str(object_id))

        assert result is not None
        assert result["id"] == str(object_id)
        assert result["title"] == "Legacy Video"

    async def test_find_by_id_not_found(self, adapter, mock_resource):
        """Test find_by_id when document not found."""
        mock_resource["resource"].find_one.return_value = None

        result = await adapter.find_by_id("videos", "nonexistent")

        assert result is None

    # =========================================================================
    # Find Tests
    # =========================================================================

    async def test_find_returns_id_field(self, adapter, mock_resource):
        """Test that find returns documents with 'id' field."""
        cursor_mock = MagicMock()
        cursor_mock.sort = MagicMock(return_value=cursor_mock)
        cursor_mock.skip = MagicMock(return_value=cursor_mock)
        cursor_mock.limit = MagicMock(return_value=cursor_mock)
        cursor_mock.to_list = AsyncMock(
            return_value=[
                {"_id": "uuid-1", "title": "Video 1"},
                {"_id": "uuid-2", "title": "Video 2"},
            ]
        )

        mock_resource["collection"].find = MagicMock(return_value=cursor_mock)

        results = await adapter.find("videos", {"status": "ready"})

        assert len(results) == 2
        assert all("id" in doc for doc in results)
        assert all("_id" not in doc for doc in results)
        assert results[0]["id"] == "uuid-1"
        assert results[1]["id"] == "uuid-2"

    # =========================================================================
    # Find One Tests
    # =========================================================================

    async def test_find_one_returns_id_field(self, adapter, mock_resource):
        """Test that find_one returns document with 'id' field."""
        mock_resource["resource"].find_one.return_value = {
            "_id": "test-uuid",
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }

        result = await adapter.find_one("videos", {"youtube_id": "dQw4w9WgXcQ"})

        assert result is not None
        assert "id" in result
        assert result["id"] == "test-uuid"
        assert "_id" not in result

    async def test_find_one_not_found(self, adapter, mock_resource):
        """Test find_one when no document matches."""
        mock_resource["resource"].find_one.return_value = None

        result = await adapter.find_one("videos", {"youtube_id": "nonexistent"})

        assert result is None

    # =========================================================================
    # Update Tests
    # =========================================================================

    async def test_update_with_uuid_string_id(self, adapter, mock_resource):
        """Test update with UUID string ID."""
        # find_one returns existing doc, then update_one is called
        mock_resource["resource"].find_one.return_value = {
            "_id": "test-uuid",
            "status": "pending",
        }
        mock_resource["resource"].update_one = AsyncMock()

        updates = {"status": "ready", "id": "test-uuid"}

        result = await adapter.update("videos", "test-uuid", updates)

        # Should find by string _id
        mock_resource["resource"].find_one.assert_called_with(
            "videos", {"_id": "test-uuid"}
        )

        # Updates should have 'id' converted to '_id'
        call_args = mock_resource["resource"].update_one.call_args
        update_doc = call_args[0][2]["$set"]
        assert "_id" in update_doc
        assert "id" not in update_doc

        assert result is True

    async def test_update_not_found(self, adapter, mock_resource):
        """Test update when document not found."""
        mock_resource["resource"].find_one.return_value = None

        result = await adapter.update("videos", "nonexistent-uuid", {"status": "ready"})

        assert result is False

    # =========================================================================
    # Delete Tests
    # =========================================================================

    async def test_delete_with_uuid_string_id(self, adapter, mock_resource):
        """Test delete with UUID string ID."""
        mock_resource["resource"].delete_one.return_value = 1

        result = await adapter.delete("videos", "test-uuid")

        # Should search by string _id
        mock_resource["resource"].delete_one.assert_called_with(
            "videos", {"_id": "test-uuid"}
        )
        assert result is True

    async def test_delete_falls_back_to_objectid(self, adapter, mock_resource):
        """Test delete falls back to ObjectId for legacy documents."""
        object_id = ObjectId()

        # First call: string ID not deleted, second call: ObjectId deleted
        mock_resource["resource"].delete_one.side_effect = [0, 1]

        result = await adapter.delete("videos", str(object_id))

        assert result is True
        assert mock_resource["resource"].delete_one.call_count == 2

    async def test_delete_not_found(self, adapter, mock_resource):
        """Test delete when document not found."""
        mock_resource["resource"].delete_one.return_value = 0

        result = await adapter.delete("videos", "nonexistent")

        assert result is False

    # =========================================================================
    # Delete Many Tests
    # =========================================================================

    async def test_delete_many(self, adapter, mock_resource):
        """Test delete_many removes multiple documents."""
        mock_resource["collection"].delete_many = AsyncMock(
            return_value=MagicMock(deleted_count=5)
        )

        result = await adapter.delete_many("videos", {"status": "failed"})

        mock_resource["collection"].delete_many.assert_called_with({"status": "failed"})
        assert result == 5

    # =========================================================================
    # Count Tests
    # =========================================================================

    async def test_count_with_filters(self, adapter, mock_resource):
        """Test count with filters."""
        mock_resource["resource"].count.return_value = 10

        result = await adapter.count("videos", {"status": "ready"})

        mock_resource["resource"].count.assert_called_with(
            "videos", {"status": "ready"}
        )
        assert result == 10

    async def test_count_without_filters(self, adapter, mock_resource):
        """Test count without filters passes empty dict."""
        mock_resource["resource"].count.return_value = 100

        result = await adapter.count("videos")

        mock_resource["resource"].count.assert_called_with("videos", {})
        assert result == 100

    # =========================================================================
    # Integration-style Tests (ID consistency)
    # =========================================================================

    async def test_insert_and_find_by_id_roundtrip(self, adapter, mock_resource):
        """Test that insert + find_by_id preserves the ID correctly."""
        test_uuid = str(uuid4())

        # Mock insert
        mock_resource["resource"].insert_one.return_value = test_uuid

        # Mock find returning what was inserted
        mock_resource["resource"].find_one.return_value = {
            "_id": test_uuid,
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }

        # Insert document with 'id'
        document = {
            "id": test_uuid,
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }
        inserted_id = await adapter.insert("videos", document)

        # Find by the returned ID
        found = await adapter.find_by_id("videos", inserted_id)

        # The found document should have the same 'id'
        assert found is not None
        assert found["id"] == test_uuid
        assert found["youtube_id"] == "dQw4w9WgXcQ"
