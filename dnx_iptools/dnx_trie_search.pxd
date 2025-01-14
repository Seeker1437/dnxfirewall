#!/usr/bin/env python3

cdef struct l1_recurve:
    long id
    short l2_size
    l2_recurve *l2_ptr

cdef struct l2_recurve:
    long id
    short host_category

cdef struct l1_range:
    long id
    short l2_size
    l2_range *l2_ptr

cdef struct l2_range:
    long network_id
    long broadcast_id
    short country_code


cdef class RecurveTrie:

    cdef:

        l1_recurve *L1_CONTAINER
        l2_recurve *L2_CONTAINER

        size_t L1_SIZE
        size_t L2_SIZE

    cdef l2_recurve* make_l2(self, (long, long) l2_entry)
    cdef long _l1_search(self, (long, long) container_ids) nogil
    cdef long _l2_search(self, long container_id, short l2_size, l2_recurve **L2_CONTAINER) nogil

cdef class RangeTrie:

    cdef:

        l1_range *L1_CONTAINER
        l2_range *L2_CONTAINER

        size_t L1_SIZE
        size_t L2_SIZE

    cdef l2_range* make_l2(self, (long, long, short) l2_entry)
    cdef long _search(self, (long, long) container_ids) nogil