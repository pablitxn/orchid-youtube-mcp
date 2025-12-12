"""Unit tests for MongoDB document database provider."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from bson import ObjectId


class TestMongoDBDocumentDB:
    """Tests for MongoDBDocumentDB provider.

    These tests verify the ID mapping behavior between domain model 'id'
    and MongoDB's '_id' field.
    """

    @pytest.fixture
    def mock_motor_client(self):
        """Create a mock Motor client."""
        with patch(
            "src.commons.infrastructure.documentdb.mongodb_provider.AsyncIOMotorClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_db = MagicMock()
            mock_collection = MagicMock()

            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)

            mock_client_class.return_value = mock_client

            yield {
                "client_class": mock_client_class,
                "client": mock_client,
                "db": mock_db,
                "collection": mock_collection,
            }

    @pytest.fixture
    def mongodb_provider(self, mock_motor_client):
        """Create MongoDB provider with mocked client."""
        from src.commons.infrastructure.documentdb.mongodb_provider import (
            MongoDBDocumentDB,
        )

        provider = MongoDBDocumentDB(
            connection_string="mongodb://localhost:27017",
            database_name="test_db",
        )
        # Replace the internal db reference with our mock
        provider._db = mock_motor_client["db"]
        provider._client = mock_motor_client["client"]
        return provider

    # =========================================================================
    # Insert Tests
    # =========================================================================

    async def test_insert_uses_id_as_mongodb_id(
        self, mongodb_provider, mock_motor_client
    ):
        """Test that insert uses document 'id' as MongoDB '_id'."""
        collection = mock_motor_client["collection"]
        collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="test-uuid-123")
        )

        document = {
            "id": "test-uuid-123",
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }

        result = await mongodb_provider.insert("videos", document)

        # Verify the document was transformed
        call_args = collection.insert_one.call_args[0][0]
        assert "_id" in call_args
        assert call_args["_id"] == "test-uuid-123"
        assert "id" not in call_args  # 'id' should be removed

        assert result == "test-uuid-123"

    async def test_insert_without_id_field(self, mongodb_provider, mock_motor_client):
        """Test insert when document doesn't have 'id' field."""
        collection = mock_motor_client["collection"]
        mongo_id = ObjectId()
        collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id=mongo_id))

        document = {
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }

        result = await mongodb_provider.insert("videos", document)

        # Should use MongoDB's generated ObjectId
        assert result == str(mongo_id)

    async def test_insert_does_not_modify_original_document(
        self, mongodb_provider, mock_motor_client
    ):
        """Test that insert doesn't modify the original document."""
        collection = mock_motor_client["collection"]
        collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="test-uuid")
        )

        original_document = {
            "id": "test-uuid",
            "title": "Test",
        }

        await mongodb_provider.insert("videos", original_document)

        # Original document should be unchanged
        assert "id" in original_document
        assert "_id" not in original_document

    # =========================================================================
    # Insert Many Tests
    # =========================================================================

    async def test_insert_many_uses_id_as_mongodb_id(
        self, mongodb_provider, mock_motor_client
    ):
        """Test that insert_many uses document 'id' as MongoDB '_id'."""
        collection = mock_motor_client["collection"]
        collection.insert_many = AsyncMock(
            return_value=MagicMock(inserted_ids=["uuid-1", "uuid-2"])
        )

        documents = [
            {"id": "uuid-1", "title": "Video 1"},
            {"id": "uuid-2", "title": "Video 2"},
        ]

        result = await mongodb_provider.insert_many("videos", documents)

        # Verify all documents were transformed
        call_args = collection.insert_many.call_args[0][0]
        assert len(call_args) == 2
        assert all("_id" in doc for doc in call_args)
        assert all("id" not in doc for doc in call_args)
        assert call_args[0]["_id"] == "uuid-1"
        assert call_args[1]["_id"] == "uuid-2"

        assert result == ["uuid-1", "uuid-2"]

    async def test_insert_many_empty_list(self, mongodb_provider, mock_motor_client):
        """Test insert_many with empty list."""
        result = await mongodb_provider.insert_many("videos", [])
        assert result == []

    # =========================================================================
    # Find By ID Tests
    # =========================================================================

    async def test_find_by_id_with_uuid_string(
        self, mongodb_provider, mock_motor_client
    ):
        """Test find_by_id with UUID string ID."""
        collection = mock_motor_client["collection"]
        collection.find_one = AsyncMock(
            return_value={
                "_id": "test-uuid-123",
                "youtube_id": "dQw4w9WgXcQ",
                "title": "Test Video",
            }
        )

        result = await mongodb_provider.find_by_id("videos", "test-uuid-123")

        # Should search by string _id first
        collection.find_one.assert_called_with({"_id": "test-uuid-123"})

        # Result should have 'id' instead of '_id'
        assert result is not None
        assert "id" in result
        assert result["id"] == "test-uuid-123"
        assert "_id" not in result

    async def test_find_by_id_falls_back_to_objectid(
        self, mongodb_provider, mock_motor_client
    ):
        """Test find_by_id falls back to ObjectId for legacy documents."""
        collection = mock_motor_client["collection"]
        object_id = ObjectId()

        # First call returns None (string ID not found)
        # Second call returns document (found by ObjectId)
        collection.find_one = AsyncMock(
            side_effect=[
                None,
                {
                    "_id": object_id,
                    "youtube_id": "dQw4w9WgXcQ",
                    "title": "Legacy Video",
                },
            ]
        )

        result = await mongodb_provider.find_by_id("videos", str(object_id))

        assert result is not None
        assert result["id"] == str(object_id)
        assert result["title"] == "Legacy Video"

    async def test_find_by_id_not_found(self, mongodb_provider, mock_motor_client):
        """Test find_by_id when document not found."""
        collection = mock_motor_client["collection"]
        collection.find_one = AsyncMock(return_value=None)

        result = await mongodb_provider.find_by_id("videos", "nonexistent")

        assert result is None

    # =========================================================================
    # Find Tests
    # =========================================================================

    async def test_find_returns_id_field(self, mongodb_provider, mock_motor_client):
        """Test that find returns documents with 'id' field."""
        collection = mock_motor_client["collection"]

        # Create async iterator mock
        async def mock_cursor():
            yield {"_id": "uuid-1", "title": "Video 1"}
            yield {"_id": "uuid-2", "title": "Video 2"}

        cursor_mock = MagicMock()
        cursor_mock.sort = MagicMock(return_value=cursor_mock)
        cursor_mock.skip = MagicMock(return_value=cursor_mock)
        cursor_mock.limit = MagicMock(return_value=cursor_mock)
        cursor_mock.__aiter__ = lambda self: mock_cursor()

        collection.find = MagicMock(return_value=cursor_mock)

        results = await mongodb_provider.find("videos", {"status": "ready"})

        assert len(results) == 2
        assert all("id" in doc for doc in results)
        assert all("_id" not in doc for doc in results)
        assert results[0]["id"] == "uuid-1"
        assert results[1]["id"] == "uuid-2"

    # =========================================================================
    # Find One Tests
    # =========================================================================

    async def test_find_one_returns_id_field(self, mongodb_provider, mock_motor_client):
        """Test that find_one returns document with 'id' field."""
        collection = mock_motor_client["collection"]
        collection.find_one = AsyncMock(
            return_value={
                "_id": "test-uuid",
                "youtube_id": "dQw4w9WgXcQ",
                "title": "Test Video",
            }
        )

        result = await mongodb_provider.find_one(
            "videos", {"youtube_id": "dQw4w9WgXcQ"}
        )

        assert result is not None
        assert "id" in result
        assert result["id"] == "test-uuid"
        assert "_id" not in result

    async def test_find_one_not_found(self, mongodb_provider, mock_motor_client):
        """Test find_one when no document matches."""
        collection = mock_motor_client["collection"]
        collection.find_one = AsyncMock(return_value=None)

        result = await mongodb_provider.find_one(
            "videos", {"youtube_id": "nonexistent"}
        )

        assert result is None

    # =========================================================================
    # Update Tests
    # =========================================================================

    async def test_update_with_uuid_string_id(
        self, mongodb_provider, mock_motor_client
    ):
        """Test update with UUID string ID."""
        collection = mock_motor_client["collection"]
        collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1, modified_count=1)
        )

        updates = {"status": "ready", "id": "test-uuid"}

        result = await mongodb_provider.update("videos", "test-uuid", updates)

        # Should search by string _id
        call_args = collection.update_one.call_args
        assert call_args[0][0] == {"_id": "test-uuid"}

        # Updates should have 'id' converted to '_id'
        update_doc = call_args[0][1]["$set"]
        assert "_id" in update_doc
        assert "id" not in update_doc

        assert result is True

    async def test_update_falls_back_to_objectid(
        self, mongodb_provider, mock_motor_client
    ):
        """Test update falls back to ObjectId for legacy documents."""
        collection = mock_motor_client["collection"]
        object_id = ObjectId()

        # First call: string ID not matched
        # Second call: ObjectId matched
        collection.update_one = AsyncMock(
            side_effect=[
                MagicMock(matched_count=0, modified_count=0),
                MagicMock(matched_count=1, modified_count=1),
            ]
        )

        result = await mongodb_provider.update(
            "videos", str(object_id), {"status": "ready"}
        )

        assert result is True
        assert collection.update_one.call_count == 2

    async def test_update_returns_true_when_matched_but_not_modified(
        self, mongodb_provider, mock_motor_client
    ):
        """Test update returns True when document matched but values unchanged."""
        collection = mock_motor_client["collection"]
        collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1, modified_count=0)
        )

        result = await mongodb_provider.update(
            "videos", "test-uuid", {"status": "ready"}
        )

        # Should return True because document was found (matched)
        assert result is True

    async def test_update_not_found(self, mongodb_provider, mock_motor_client):
        """Test update when document not found."""
        collection = mock_motor_client["collection"]
        collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0, modified_count=0)
        )

        result = await mongodb_provider.update(
            "videos", "nonexistent-uuid", {"status": "ready"}
        )

        assert result is False

    # =========================================================================
    # Delete Tests
    # =========================================================================

    async def test_delete_with_uuid_string_id(
        self, mongodb_provider, mock_motor_client
    ):
        """Test delete with UUID string ID."""
        collection = mock_motor_client["collection"]
        collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        result = await mongodb_provider.delete("videos", "test-uuid")

        # Should search by string _id
        collection.delete_one.assert_called_with({"_id": "test-uuid"})
        assert result is True

    async def test_delete_falls_back_to_objectid(
        self, mongodb_provider, mock_motor_client
    ):
        """Test delete falls back to ObjectId for legacy documents."""
        collection = mock_motor_client["collection"]
        object_id = ObjectId()

        # First call: string ID not deleted
        # Second call: ObjectId deleted
        collection.delete_one = AsyncMock(
            side_effect=[
                MagicMock(deleted_count=0),
                MagicMock(deleted_count=1),
            ]
        )

        result = await mongodb_provider.delete("videos", str(object_id))

        assert result is True
        assert collection.delete_one.call_count == 2

    async def test_delete_not_found(self, mongodb_provider, mock_motor_client):
        """Test delete when document not found."""
        collection = mock_motor_client["collection"]
        collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))

        result = await mongodb_provider.delete("videos", "nonexistent")

        assert result is False

    # =========================================================================
    # Delete Many Tests
    # =========================================================================

    async def test_delete_many(self, mongodb_provider, mock_motor_client):
        """Test delete_many removes multiple documents."""
        collection = mock_motor_client["collection"]
        collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=5))

        result = await mongodb_provider.delete_many("videos", {"status": "failed"})

        collection.delete_many.assert_called_with({"status": "failed"})
        assert result == 5

    # =========================================================================
    # Count Tests
    # =========================================================================

    async def test_count_with_filters(self, mongodb_provider, mock_motor_client):
        """Test count with filters."""
        collection = mock_motor_client["collection"]
        collection.count_documents = AsyncMock(return_value=10)

        result = await mongodb_provider.count("videos", {"status": "ready"})

        collection.count_documents.assert_called_with({"status": "ready"})
        assert result == 10

    async def test_count_without_filters(self, mongodb_provider, mock_motor_client):
        """Test count without filters uses estimated count."""
        collection = mock_motor_client["collection"]
        collection.estimated_document_count = AsyncMock(return_value=100)

        result = await mongodb_provider.count("videos")

        collection.estimated_document_count.assert_called_once()
        assert result == 100

    # =========================================================================
    # Integration-style Tests (ID consistency)
    # =========================================================================

    async def test_insert_and_find_by_id_roundtrip(
        self, mongodb_provider, mock_motor_client
    ):
        """Test that insert + find_by_id preserves the ID correctly."""
        collection = mock_motor_client["collection"]
        test_uuid = str(uuid4())

        # Mock insert
        collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id=test_uuid))

        # Mock find returning what was inserted
        collection.find_one = AsyncMock(
            return_value={
                "_id": test_uuid,
                "youtube_id": "dQw4w9WgXcQ",
                "title": "Test Video",
            }
        )

        # Insert document with 'id'
        document = {
            "id": test_uuid,
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
        }
        inserted_id = await mongodb_provider.insert("videos", document)

        # Find by the returned ID
        found = await mongodb_provider.find_by_id("videos", inserted_id)

        # The found document should have the same 'id'
        assert found is not None
        assert found["id"] == test_uuid
        assert found["youtube_id"] == "dQw4w9WgXcQ"

    async def test_insert_update_find_roundtrip(
        self, mongodb_provider, mock_motor_client
    ):
        """Test insert + update + find preserves ID correctly."""
        collection = mock_motor_client["collection"]
        test_uuid = str(uuid4())

        # Mock insert
        collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id=test_uuid))

        # Mock update
        collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1, modified_count=1)
        )

        # Mock find returning updated document
        collection.find_one = AsyncMock(
            return_value={
                "_id": test_uuid,
                "youtube_id": "dQw4w9WgXcQ",
                "title": "Test Video",
                "status": "ready",
            }
        )

        # Insert
        document = {
            "id": test_uuid,
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "status": "pending",
        }
        inserted_id = await mongodb_provider.insert("videos", document)

        # Update
        await mongodb_provider.update(
            "videos", inserted_id, {"status": "ready", "id": test_uuid}
        )

        # Find
        found = await mongodb_provider.find_by_id("videos", inserted_id)

        assert found is not None
        assert found["id"] == test_uuid
        assert found["status"] == "ready"
