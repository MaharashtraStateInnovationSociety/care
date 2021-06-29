from collections import defaultdict
import io
import hashlib
from datetime import date, datetime
from pyexcel_xls import get_data as xls_get
import pandas
import magic
from django.utils.timezone import make_aware
from django.conf import settings
from django.utils.datastructures import MultiValueDictKeyError
from django_filters import rest_framework as filters
from django_filters import Filter
from django_filters.filters import DateFromToRangeFilter
from djqscsv import render_to_csv_response
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.mixins import DestroyModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet


from care.facility.api.serializers.patient_external_test import (
    PatientExternalTestSerializer, PatientExternalTestICMRDataSerializer
)
from care.facility.models import PatientExternalTest, PatientExternalTestUploadHistory
from care.users.models import User, State, District


def prettyerrors(errors):
    pretty_errors = defaultdict(list)
    for attribute in PatientExternalTest.HEADER_CSV_MAPPING.keys():
        if attribute in errors:
            for error in errors.get(attribute, ""):
                pretty_errors[attribute].append(str(error))
    return dict(pretty_errors)


class MFilter(Filter):
    def filter(self, qs, value):
        if not value:
            return qs
        values = value.split(",")
        _filter = {
            self.field_name + "__in": values,
            self.field_name + "__isnull": False,
        }
        qs = qs.filter(**_filter)
        return qs


class PatientExternalTestFilter(filters.FilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    srf_id = filters.CharFilter(field_name="srf_id", lookup_expr="icontains")
    mobile_number = filters.CharFilter(field_name="mobile_number", lookup_expr="icontains")
    wards = MFilter(field_name="ward__id")
    districts = MFilter(field_name="district__id")
    local_bodies = MFilter(field_name="local_body__id")
    sample_collection_date = DateFromToRangeFilter(field_name="sample_collection_date")
    result_date = DateFromToRangeFilter(field_name="result_date")
    created_date = DateFromToRangeFilter(field_name="created_date")


class PatientExternalTestViewSet(
    RetrieveModelMixin, ListModelMixin, DestroyModelMixin, GenericViewSet,
):
    serializer_class = PatientExternalTestSerializer
    queryset = PatientExternalTest.objects.select_related("ward", "local_body", "district").all().order_by("-id")
    permission_classes = (IsAuthenticated,)
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = PatientExternalTestFilter
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_queryset(self):
        queryset = self.queryset
        if not self.request.user.is_superuser:
            if self.request.user.user_type >= User.TYPE_VALUE_MAP["StateLabAdmin"]:
                queryset = queryset.filter(district__state=self.request.user.state)
            elif self.request.user.user_type >= User.TYPE_VALUE_MAP["DistrictLabAdmin"]:
                queryset = queryset.filter(district=self.request.user.district)
            elif self.request.user.user_type >= User.TYPE_VALUE_MAP["LocalBodyAdmin"]:
                queryset = queryset.filter(local_body=self.request.user.local_body)
            elif self.request.user.user_type >= User.TYPE_VALUE_MAP["WardAdmin"]:
                queryset = queryset.filter(ward=self.request.user.ward, ward__isnull=False)
            else:
                queryset = queryset.none()
        return queryset

    def destroy(self, request, *args, **kwargs):
        if self.request.user.user_type < User.TYPE_VALUE_MAP["DistrictLabAdmin"]:
            raise PermissionDenied()
        return super().destroy(request, *args, **kwargs)

    def check_upload_permission(self):
        if (
            self.request.user.is_superuser == True
            or self.request.user.user_type >= User.TYPE_VALUE_MAP["DistrictLabAdmin"]
        ):
            return True
        return False

    def list(self, request, *args, **kwargs):
        if settings.CSV_REQUEST_PARAMETER in request.GET:
            mapping = PatientExternalTest.CSV_MAPPING.copy()
            pretty_mapping = PatientExternalTest.CSV_MAKE_PRETTY.copy()
            queryset = self.filter_queryset(self.get_queryset()).values(*mapping.keys())
            return render_to_csv_response(queryset, field_header_map=mapping, field_serializer_map=pretty_mapping)
        return super(PatientExternalTestViewSet, self).list(request, *args, **kwargs)

    @action(methods=["POST"], detail=False)
    def bulk_upsert(self, request, *args, **kwargs):
        if not self.check_upload_permission():
            raise PermissionDenied("Permission to Endpoint Denied")
        # if len(request.FILES.keys()) != 1:
        #     raise ValidationError({"file": "Upload 1 File at a time"})
        # csv_file = request.FILES[list(request.FILES.keys())[0]]
        # csv_file.seek(0)
        # reader = csv.DictReader(io.StringIO(csv_file.read().decode("utf-8-sig")))
        if "sample_tests" not in request.data:
            raise ValidationError({"sample_tests": "No Data was provided"})
        if type(request.data["sample_tests"]) != type([]):
            raise ValidationError({"sample_tests": "Data should be provided as a list"})
        errors = {}
        counter = 0
        ser_objects = []
        invalid = False
        for sample in request.data["sample_tests"]:
            counter += 1
            serialiser_obj = PatientExternalTestSerializer(data=sample)
            valid = serialiser_obj.is_valid()
            current_error = prettyerrors(serialiser_obj._errors)
            if current_error and (not valid):
                errors[counter] = current_error
                invalid = True
            ser_objects.append(serialiser_obj)
        if invalid:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        for ser_object in ser_objects:
            ser_object.save()
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(methods=["POST"], detail=False)
    def bulk_upsert_icmr(self, request, *args, **kwargs):
        if not self.check_upload_permission():
            raise PermissionDenied("Permission to Endpoint Denied")
        parsed_data = []

        states = State.objects.all().prefetch_related("districts")
        districts = District.objects.all()
        states_dict = {state.name.lower(): state for state in states}
        districts_dict = {district.name.lower(): district for district in districts}

        excel_data = {}
        uploaded_file = request.FILES["file"]

        file_hash = hashlib.blake2b()

        while True:
            chunk = uploaded_file.read(16384)
            if not chunk:
                break
            file_hash.update(chunk)
        existing_file_hash = PatientExternalTestUploadHistory.objects.filter(hash=file_hash.hexdigest())

        if existing_file_hash.exists():
            return Response(data="This file has already been uploaded.", status=status.HTTP_400_BAD_REQUEST)

        uploaded_file.seek(0)
        file_read = uploaded_file.read()

        mime = magic.Magic(mime=True)
        mime_type = mime.from_buffer(file_read)
        extension = str(uploaded_file).split('.')[-1]

        if mime_type == "application/vnd.ms-excel":
            excel_data = xls_get(uploaded_file, column_limit=41)
            parsed_data = self.parse_excel(excel_data=excel_data, states_dict=states_dict,
                                           districts_dict=districts_dict)

        elif mime_type == "text/plain" and extension == "xls":
            # assuming the file is uploaded as is when exported from icmr portal
            # icmr portal file has an extension of .xls but actually is a tabbed csv file in plaintext format
            file_stream = io.StringIO(file_read.decode('utf-8'))
            csv_data = pandas.read_csv(file_stream, delimiter='\t').to_dict('records')
            parsed_data = self.parse_tabbed_csv(
                csv_data=csv_data, states_dict=states_dict, districts_dict=districts_dict)

        PatientExternalTest.objects.bulk_create(parsed_data, ignore_conflicts=True)
        # serializer = PatientExternalTestICMRDataSerializer(data=parsed_data, many=True)
        # serializer.is_valid(raise_exception=True)
        # serializer.save()

        PatientExternalTestUploadHistory.objects.create(file_name=str(
            uploaded_file), uploaded_by=request.user, hash=file_hash.hexdigest(),
            most_recent_date_of_sample_tested_in_file=self.most_recent_date_of_sample_tested_in_file)

        response_message = "Tests were successfully uploaded and saved"
        response = {"message": response_message}
        return Response(data=response, status=status.HTTP_200_OK)

    def parse_tabbed_csv(self, csv_data, states_dict, districts_dict):
        parsed_data = []
        self.most_recent_date_of_sample_tested_in_file = None
        for row in csv_data:
            dictionary = {}

            for key, item in row.items():
                key, value = self.parse_dictionary(key=key.strip(), item=item,
                                                   states_dict=states_dict, districts_dict=districts_dict)
                dictionary[key] = value

            if dictionary:
                parsed_data.append(PatientExternalTest(**dictionary))

        return parsed_data

    def parse_excel(self, excel_data, states_dict, districts_dict):
        self.most_recent_date_of_sample_tested_in_file = None
        parsed_data = []
        file_name = list(excel_data.keys())[0]
        keys = []

        for i, row in enumerate(excel_data.get(file_name)):

            if i == 0:
                keys = [item.strip() for item in row]
            else:
                dictionary = {}

                for j, item in enumerate(row):
                    key, value = self.parse_dictionary(
                        key=keys[j], item=item, states_dict=states_dict, districts_dict=districts_dict)
                    dictionary[key] = value

                if dictionary:
                    parsed_data.append(PatientExternalTest(**dictionary))

        return parsed_data

    def parse_dictionary(self, key, item, states_dict, districts_dict):

        if isinstance(item, str):
            item = item.strip()
        key = PatientExternalTest.ICMR_EXCEL_HEADER_KEY_MAPPING.get(key)

        if key == "state":
            state = states_dict.get(item.lower())

            if state:
                item = state.id
            key = "state_id"

        elif key == "district":
            district = districts_dict.get(item.lower())

            if district:
                item = district.id
            key = "district_id"

        elif key in ["is_hospitalized", "is_repeat"]:

            if item and "yes" in item:
                item = True
            else:
                item = False

        elif key in ["hospitalization_date", "confirmation_date", "sample_received_date", "entry_date"]:
            if "N/A" in item:
                item = None
            elif item:
                item = make_aware(datetime.strptime(item, "%Y-%m-%d %H:%M:%S"))

        elif key in ["sample_collection_date"]:
            item = make_aware(datetime.strptime(item, "%Y-%m-%d %H:%M:%S")).date()

        elif key == "date_of_sample_tested":
            item = make_aware(datetime.strptime(item, "%Y-%m-%d %H:%M:%S"))
            if self.most_recent_date_of_sample_tested_in_file is None or self.most_recent_date_of_sample_tested_in_file < item:
                self.most_recent_date_of_sample_tested_in_file = item

        return key, item
