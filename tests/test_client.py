import unittest
import asyncio

from sma.api.client import APIClient


class TestAPIClientMock(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = APIClient(use_mock=True)

    async def asyncTearDown(self):
        await self.client.close()

    async def test_get_students_basic(self):
        students = await self.client.get_students()
        self.assertEqual(len(students), 50)
        # توزیع حداقلی را چک می‌کنیم
        genders = [s.gender for s in students]
        self.assertTrue(10 <= genders.count(0) <= 25)  # حدود 30%
        self.assertTrue(25 <= [s for s in students if s.center == 1].__len__() <= 30)  # حدود 50%

    async def test_get_mentors_basic(self):
        mentors = await self.client.get_mentors()
        self.assertEqual(len(mentors), 15)
        self.assertTrue(all(m.is_active for m in mentors))

    async def test_create_allocation_and_stats(self):
        students = await self.client.get_students({"school_type": "normal"})
        mentors = await self.client.get_mentors()
        # انتخاب یک جفت سازگار (جنسیت/مرکز/گروه/غیرمدرسه‌ای)
        target_student = None
        target_mentor = None
        for s in students:
            for m in mentors:
                if (
                    s.gender == m.gender
                    and s.center in m.allowed_centers
                    and s.level in m.allowed_groups
                    and not m.is_school_mentor
                    and m.current_load < m.capacity
                ):
                    target_student = s
                    target_mentor = m
                    break
            if target_student:
                break
        if target_student and target_mentor:
            alloc = await self.client.create_allocation(target_student.id, target_mentor.id)
            self.assertEqual(alloc.status, "OK")
            stats = await self.client.get_dashboard_stats()
            self.assertGreaterEqual(stats.total_allocations, 35)

    async def test_next_counter(self):
        c_male = await self.client.get_next_counter(1)
        c_female = await self.client.get_next_counter(0)
        self.assertTrue(c_male.startswith(c_male[:2]))
        self.assertEqual(len(c_male), 9)
        self.assertEqual(len(c_female), 9)


if __name__ == "__main__":
    unittest.main()
