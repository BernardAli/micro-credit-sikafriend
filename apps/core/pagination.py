from django.core.paginator import Paginator


def build_pagination_query(request, *, page_param="page"):
    params = request.GET.copy()
    params.pop(page_param, None)
    return params.urlencode()


def paginate_items(request, items, *, per_page=12, page_param="page"):
    paginator = Paginator(items, per_page)
    page_obj = paginator.get_page(request.GET.get(page_param) or 1)
    page_numbers = [
        None if value == paginator.ELLIPSIS else value
        for value in paginator.get_elided_page_range(
            number=page_obj.number,
            on_each_side=1,
            on_ends=1,
        )
    ]
    return {
        "page_obj": page_obj,
        "page_numbers": page_numbers,
        "pagination_query": build_pagination_query(request, page_param=page_param),
    }
