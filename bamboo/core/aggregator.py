from pandas import concat

from bamboo.core.aggregations import AGGREGATIONS
from bamboo.core.frame import add_parent_column, rows_for_parent_id
from bamboo.lib.parsing import parse_columns


def group_join(groups, left, other):
    if groups:
        other.set_index(groups, inplace=True)

    return left.join(other, on=groups if len(groups) else None)


def aggregated_dataset(dataset, dframe, groups):
    """Create an aggregated dataset for this dataset.

    Creates and saves a dataset from the given `dframe`.  Then stores this
    dataset as an aggregated dataset given `groups` for `self`.

    :param dframe: The DataFrame to store in the new aggregated dataset.
    :param groups: The groups associated with this aggregated dataset.
    :returns: The newly created aggregated dataset.
    """
    a_dataset = dataset.create()
    a_dataset.save_observations(dframe)

    # store a link to the new dataset
    group_str = dataset.join_groups(groups)
    a_datasets_dict = dataset.aggregated_datasets_dict
    a_datasets_dict[group_str] = a_dataset.dataset_id
    dataset.update({dataset.AGGREGATED_DATASETS: a_datasets_dict})

    return a_dataset


class Aggregator(object):
    """Perform a aggregations on datasets.

    Apply the `aggregation` to group columns by `groups` and the `columns`
    of the `dframe`. Store the resulting `dframe` as a linked dataset for
    `dataset`. If a linked dataset with the same groups already exists update
    this dataset.  Otherwise create a new linked dataset.
    """

    def __init__(self, dframe, groups, _type, name, columns):
        """Create an Aggregator.

        :param columns: The columns to aggregate over.
        :param dframe: The DataFrame to aggregate.
        :param groups: A list of columns to group on.
        :param _type: The aggregation to perform.
        :param name: The name of the aggregation.
        """
        self.columns = columns
        self.dframe = dframe
        self.groups = groups
        self.name = name
        aggregation = AGGREGATIONS.get(_type)
        self.aggregation = aggregation(self.name, self.groups, self.dframe)

    def save(self, dataset):
        """Save this aggregation.

        If an aggregated dataset for this aggregations group already exists
        store in this dataset, if not create a new aggregated dataset and store
        the aggregation in this new aggregated dataset.

        """
        new_dframe = self.aggregation.eval(self.columns)
        new_dframe = add_parent_column(new_dframe, dataset.dataset_id)

        a_dataset = dataset.aggregated_dataset(self.groups)

        if a_dataset is None:
            a_dataset = aggregated_dataset(dataset, new_dframe, self.groups)
        else:
            a_dframe = a_dataset.dframe()
            new_dframe = group_join(self.groups, a_dframe, new_dframe)
            a_dataset.replace_observations(new_dframe)

        self.new_dframe = new_dframe

    def update(self, dataset, child_dataset, formula, reducible):
        """Attempt to reduce an update and store."""
        parent_dataset_id = dataset.dataset_id

        # get dframe only including rows from this parent
        dframe = rows_for_parent_id(child_dataset.dframe(
            keep_parent_ids=True, reload_=True), parent_dataset_id)

        # remove rows in child from parent
        child_dataset.remove_parent_observations(parent_dataset_id)

        if reducible and self.__is_reducible():
            dframe = self.aggregation.reduce(dframe, self.columns)
        else:
            dframe = self.updated_dframe(dataset, formula, dframe)

        new_a_dframe = concat([child_dataset.dframe(), dframe])
        new_a_dframe = add_parent_column(new_a_dframe, parent_dataset_id)
        child_dataset.replace_observations(new_a_dframe)

        return child_dataset.dframe()

    def updated_dframe(self, dataset, formula, dframe):
        """Create a new aggregation and update return updated dframe."""
        # build column arguments from original dframe
        columns = parse_columns(dataset, formula, self.name, self.dframe)
        new_dframe = self.aggregation.eval(columns)

        new_columns = [x for x in new_dframe.columns if x not in self.groups]

        dframe = dframe.drop(new_columns, axis=1)
        dframe = group_join(self.groups, new_dframe, dframe)

        return dframe

    def __is_reducible(self):
        """If it is not grouped and a reduce is defined."""
        return not self.groups and 'reduce' in dir(self.aggregation)
